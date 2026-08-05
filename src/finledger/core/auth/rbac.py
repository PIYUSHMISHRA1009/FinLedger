"""
FinLedger RBAC (Role-Based Access Control) Module

Provides permission checking and role validation.
"""

from functools import wraps
from typing import List, Optional, Set, Callable
from uuid import UUID

from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from finledger.api.config.settings import get_settings
from finledger.core.auth.tokens import (
    decode_access_token,
    TokenPayload,
    get_permissions_for_role,
    is_blacklisted,
    add_to_blacklist,
)
from finledger.core.auth.password import verify_password, get_password_hash, validate_password_strength
from finledger.db.database import get_db
from finledger.db.models import User, RefreshToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from redis.asyncio import Redis


# Security scheme
security = HTTPBearer(auto_error=False)


class PermissionError(HTTPException):
    """Raised when permission check fails."""
    def __init__(self, detail: str = "Insufficient permissions"):
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


class AuthenticationError(HTTPException):
    """Raised when authentication fails."""
    def __init__(self, detail: str = "Authentication required"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )


class TokenExpiredError(AuthenticationError):
    """Raised when token is expired."""
    def __init__(self):
        super().__init__(detail="Token has expired")


class TokenRevokedError(AuthenticationError):
    """Raised when token is revoked."""
    def __init__(self):
        super().__init__(detail="Token has been revoked")


# Redis client for blacklist (initialized in main app)
_redis_client: Optional[Redis] = None


def get_redis_client() -> Optional[Redis]:
    return _redis_client


def set_redis_client(client: Redis) -> None:
    global _redis_client
    _redis_client = client


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    FastAPI dependency to get current authenticated user.
    
    Validates JWT, checks blacklist, loads user from database.
    """
    if not credentials:
        raise AuthenticationError("Missing authorization header")
    
    token = credentials.credentials
    
    # Check blacklist
    redis = get_redis_client()
    if redis:
        from finledger.core.auth.tokens import get_token_jti
        jti = get_token_jti(token)
        if jti and await is_blacklisted(redis, jti):
            raise TokenRevokedError()
    
    # Decode and validate token
    payload = decode_access_token(token)
    if not payload:
        raise AuthenticationError("Invalid or expired token")
    
    if payload.token_type != "access":
        raise AuthenticationError("Invalid token type")
    
    # Load user from database
    result = await db.execute(
        select(User).where(User.id == UUID(payload.sub))
    )
    user = result.scalar_one_or_none()
    
    if not user:
        raise AuthenticationError("User not found")
    
    if not user.is_active:
        raise AuthenticationError("Account is deactivated")
    
    return user


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """Get current user if authenticated, otherwise return None."""
    try:
        return await get_current_user(credentials, db)
    except HTTPException:
        return None


def require_permission(permission: str) -> Callable:
    """
    Dependency factory for requiring a specific permission.
    
    Usage:
        @router.get("/admin", dependencies=[Depends(require_permission("user:manage"))])
    """
    async def permission_checker(user: User = Depends(get_current_user)) -> User:
        user_permissions = get_permissions_for_role(user.role)
        if permission not in user_permissions:
            raise PermissionError(f"Requires permission: {permission}")
        return user
    
    return permission_checker


def require_role(*roles: str) -> Callable:
    """
    Dependency factory for requiring specific role(s).
    
    Usage:
        @router.get("/admin", dependencies=[Depends(require_role("ADMIN"))])
    """
    async def role_checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise PermissionError(f"Requires one of roles: {', '.join(roles)}")
        return user
    
    return role_checker


def require_any_permission(*permissions: str) -> Callable:
    """
    Dependency factory for requiring at least one of the given permissions.
    """
    async def permission_checker(user: User = Depends(get_current_user)) -> User:
        user_permissions = get_permissions_for_role(user.role)
        if not any(p in user_permissions for p in permissions):
            raise PermissionError(f"Requires one of permissions: {', '.join(permissions)}")
        return user
    
    return permission_checker


# Auth Service Class
class AuthService:
    """High-level authentication service."""
    
    def __init__(self, db: AsyncSession, redis: Optional[Redis] = None):
        self.db = db
        self.redis = redis
    
    async def register(
        self,
        email: str,
        password: str,
        full_name: str,
    ) -> User:
        """
        Register a new user.
        
        Raises:
            ValueError: If email exists or password is weak
        """
        # Check if email exists
        result = await self.db.execute(
            select(User).where(User.email == email)
        )
        if result.scalar_one_or_none():
            raise ValueError("Email already registered")
        
        # Validate password strength
        is_valid, error = validate_password_strength(password)
        if not is_valid:
            raise ValueError(error)
        
        # Create user
        user = User(
            email=email,
            password_hash=get_password_hash(password),
            full_name=full_name,
            role="USER",
            is_active=True,
            is_verified=False,  # Require email verification in production
        )
        
        self.db.add(user)
        await self.db.flush()
        await self.db.refresh(user)
        
        # TODO: Send verification email
        
        return user
    
    async def login(
        self,
        email: str,
        password: str,
        user_agent: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> tuple[User, str, str]:
        """
        Authenticate user and return token pair.
        
        Returns:
            Tuple of (user, access_token, refresh_token)
        
        Raises:
            ValueError: If credentials are invalid
        """
        # Find user
        result = await self.db.execute(
            select(User).where(User.email == email)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            # Simulate same timing to prevent user enumeration
            get_password_hash("dummy")
            raise ValueError("Invalid credentials")
        
        # Check account status
        if not user.is_active:
            raise ValueError("Account is deactivated")
        
        if user.locked_until and user.locked_until > datetime.now(timezone.utc):
            raise ValueError("Account is temporarily locked")
        
        # Verify password
        if not verify_password(password, user.password_hash):
            # Increment failed attempts
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= 5:
                user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=15)
            await self.db.flush()
            raise ValueError("Invalid credentials")
        
        # Reset failed attempts on success
        user.failed_login_attempts = 0
        user.locked_until = None
        user.last_login_at = datetime.now(timezone.utc)
        
        # Create token pair
        access_token = create_access_token(
            user_id=user.id,
            email=user.email,
            role=user.role,
        )
        refresh_token = create_refresh_token()
        
        # Store refresh token
        expires_at = datetime.now(timezone.utc) + timedelta(days=get_settings().JWT_REFRESH_TOKEN_EXPIRE_DAYS)
        await store_refresh_token(
            self.db,
            user_id=user.id,
            refresh_token=refresh_token,
            expires_at=expires_at,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        
        await self.db.commit()
        
        return user, access_token, refresh_token
    
    async def refresh(
        self,
        refresh_token: str,
        user_agent: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> tuple[str, str]:
        """
        Refresh access token using refresh token.
        
        Returns:
            Tuple of (new_access_token, new_refresh_token)
        
        Raises:
            ValueError: If refresh token is invalid or reused
        """
        # Hash the presented token
        token_hash = hash_token(refresh_token)
        
        # Find token in database
        result = await self.db.execute(
            select(RefreshToken).where(
                RefreshToken.token_hash == token_hash,
                RefreshToken.revoked == False,
                RefreshToken.expires_at > datetime.now(timezone.utc),
            )
        )
        token_obj = result.scalar_one_or_none()
        
        if not token_obj:
            # Check if token was already used (reuse detection)
            result = await self.db.execute(
                select(RefreshToken).where(
                    RefreshToken.token_hash == token_hash,
                    RefreshToken.revoked == True,
                )
            )
            reused_token = result.scalar_one_or_none()
            
            if reused_token:
                # REUSE DETECTED - Revoke ALL user tokens!
                await revoke_all_user_tokens(self.db, reused_token.user_id, "token_reuse_detected")
                await self.db.commit()
                raise ValueError("Token reuse detected - all sessions revoked")
            
            raise ValueError("Invalid or expired refresh token")
        
        # Get user
        result = await self.db.execute(
            select(User).where(User.id == token_obj.user_id)
        )
        user = result.scalar_one_or_none()
        
        if not user or not user.is_active:
            raise ValueError("User not found or deactivated")
        
        # Revoke current token (single-use)
        await revoke_refresh_token(self.db, token_obj, "token_refresh")
        
        # Create new token pair
        new_access_token = create_access_token(
            user_id=user.id,
            email=user.email,
            role=user.role,
        )
        new_refresh_token = create_refresh_token()
        
        # Store new refresh token
        expires_at = datetime.now(timezone.utc) + timedelta(days=get_settings().JWT_REFRESH_TOKEN_EXPIRE_DAYS)
        await store_refresh_token(
            self.db,
            user_id=user.id,
            refresh_token=new_refresh_token,
            expires_at=expires_at,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        
        await self.db.commit()
        
        return new_access_token, new_refresh_token
    
    async def logout(
        self,
        user: User,
        refresh_token: str,
        access_token: Optional[str] = None,
    ) -> None:
        """Logout user by revoking tokens."""
        # Revoke refresh token
        token_hash = hash_token(refresh_token)
        result = await self.db.execute(
            select(RefreshToken).where(
                RefreshToken.token_hash == token_hash,
                RefreshToken.user_id == user.id,
            )
        )
        token_obj = result.scalar_one_or_none()
        
        if token_obj:
            await revoke_refresh_token(self.db, token_obj, "user_logout")
        
        # Blacklist access token if provided
        if access_token:
            redis = get_redis_client()
            if redis:
                from finledger.core.auth.tokens import get_token_jti
                jti = get_token_jti(access_token)
                if jti:
                    # TTL = remaining token life
                    payload = decode_token_unsafe(access_token)
                    if payload and "exp" in payload:
                        ttl = max(1, int(payload["exp"] - time.time()))
                        await add_to_blacklist(redis, jti, ttl)
        
        await self.db.commit()
    
    async def change_password(
        self,
        user: User,
        current_password: str,
        new_password: str,
    ) -> None:
        """Change user password (revokes all sessions)."""
        if not verify_password(current_password, user.password_hash):
            raise ValueError("Current password is incorrect")
        
        is_valid, error = validate_password_strength(new_password)
        if not is_valid:
            raise ValueError(error)
        
        user.password_hash = get_password_hash(new_password)
        
        # Revoke all refresh tokens
        await revoke_all_user_tokens(self.db, user.id, "password_change")
        
        await self.db.commit()
    
    async def request_password_reset(self, email: str) -> bool:
        """Request password reset (returns True always to prevent enumeration)."""
        result = await self.db.execute(
            select(User).where(User.email == email)
        )
        user = result.scalar_one_or_none()
        
        if user:
            # TODO: Generate reset token and send email
            # user.password_reset_token = generate_secure_token()
            # user.password_reset_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
            # await self.db.commit()
            pass
        
        return True  # Always return True
    
    async def reset_password(self, token: str, new_password: str) -> bool:
        """Reset password using reset token."""
        is_valid, error = validate_password_strength(new_password)
        if not is_valid:
            raise ValueError(error)
        
        result = await self.db.execute(
            select(User).where(
                User.password_reset_token == token,
                User.password_reset_expires_at > datetime.now(timezone.utc),
            )
        )
        user = result.scalar_one_or_none()
        
        if not user:
            raise ValueError("Invalid or expired reset token")
        
        user.password_hash = get_password_hash(new_password)
        user.password_reset_token = None
        user.password_reset_expires_at = None
        
        # Revoke all sessions
        await revoke_all_user_tokens(self.db, user.id, "password_reset")
        
        await self.db.commit()
        return True


# Import time for logout
import time
from datetime import datetime, timezone, timedelta