"""
FinLedger JWT Token Module

Handles JWT access tokens (RS256) and refresh token management.
"""

import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
from uuid import UUID, uuid4

from jose import jwt, JWTError
from pydantic import BaseModel

from finledger.api.config.settings import get_settings
from finledger.core.auth.password import hash_token, verify_token, generate_secure_token


class TokenPayload(BaseModel):
    """JWT token payload structure."""
    sub: str  # user_id
    email: str
    role: str
    permissions: List[str]
    token_type: str  # "access" or "refresh"
    jti: str  # unique token identifier
    iat: int  # issued at
    exp: int  # expires at
    iss: str  # issuer
    aud: str  # audience


class TokenPair(BaseModel):
    """Access and refresh token pair."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds until access token expires


# Role to permissions mapping
ROLE_PERMISSIONS = {
    "USER": [
        "wallet:read",
        "wallet:write",
        "transfer:execute",
        "ledger:read",
        "transaction:read",
    ],
    "ADMIN": [
        "wallet:read",
        "wallet:write",
        "wallet:manage",
        "transfer:execute",
        "ledger:read",
        "ledger:write",
        "transaction:read",
        "transaction:read_all",
        "user:manage",
        "system:config",
        "audit:read",
    ],
    "COMPLIANCE": [
        "wallet:read",
        "transfer:execute",
        "ledger:read",
        "transaction:read_all",
        "fraud:read",
        "fraud:review",
        "audit:read",
    ],
    "SYSTEM": [
        "service:internal",
        "ledger:write",
        "webhook:send",
        "transaction:read_all",
    ],
}


def get_permissions_for_role(role: str) -> List[str]:
    """Get permissions for a role."""
    return ROLE_PERMISSIONS.get(role, [])


def create_access_token(
    user_id: UUID,
    email: str,
    role: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    Create a JWT access token.
    
    Args:
        user_id: User's UUID
        email: User's email
        role: User's role
        expires_delta: Custom expiration (defaults to settings)
    
    Returns:
        Encoded JWT token
    """
    settings = get_settings()
    
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    
    payload = {
        "iss": settings.JWT_ISSUER,
        "sub": str(user_id),
        "aud": settings.JWT_AUDIENCE,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "jti": str(uuid4()),
        "email": email,
        "role": role,
        "permissions": get_permissions_for_role(role),
        "token_type": "access",
    }
    
    # Load private key
    with open(settings.JWT_PRIVATE_KEY_PATH, "rb") as f:
        private_key = f.read()
    
    token = jwt.encode(payload, private_key, algorithm=settings.JWT_ALGORITHM)
    return token


def create_refresh_token() -> str:
    """Create an opaque refresh token (not JWT)."""
    return generate_secure_token(64)


def decode_access_token(token: str) -> Optional[TokenPayload]:
    """
    Decode and validate an access token.
    
    Returns:
        TokenPayload if valid, None otherwise
    """
    settings = get_settings()
    
    try:
        # Load public key
        with open(settings.JWT_PUBLIC_KEY_PATH, "rb") as f:
            public_key = f.read()
        
        payload = jwt.decode(
            token,
            public_key,
            algorithms=[settings.JWT_ALGORITHM],
            audience=settings.JWT_AUDIENCE,
            issuer=settings.JWT_ISSUER,
        )
        
        return TokenPayload(**payload)
    
    except JWTError:
        return None
    except Exception:
        return None


def decode_token_unsafe(token: str) -> Optional[Dict[str, Any]]:
    """
    Decode token without validation (for debugging/logging).
    
    WARNING: Does not verify signature!
    """
    try:
        return jwt.get_unverified_claims(token)
    except Exception:
        return None


def is_token_expired(token: str) -> bool:
    """Check if token is expired without full validation."""
    payload = decode_token_unsafe(token)
    if not payload:
        return True
    
    exp = payload.get("exp")
    if not exp:
        return True
    
    return datetime.now(timezone.utc).timestamp() > exp


def get_token_jti(token: str) -> Optional[str]:
    """Extract JTI from token without validation."""
    payload = decode_token_unsafe(token)
    if payload:
        return payload.get("jti")
    return None


# Refresh Token Database Operations
async def store_refresh_token(
    db_session,
    user_id: UUID,
    refresh_token: str,
    expires_at: datetime,
    user_agent: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> None:
    """Store refresh token hash in database."""
    from finledger.db.models import RefreshToken
    
    token_hash = hash_token(refresh_token)
    
    refresh_token_obj = RefreshToken(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=expires_at,
        user_agent=user_agent,
        ip_address=ip_address,
    )
    
    db_session.add(refresh_token_obj)
    await db_session.flush()


async def validate_refresh_token(
    db_session,
    user_id: UUID,
    refresh_token: str,
) -> Optional["RefreshToken"]:
    """
    Validate a refresh token.
    
    Returns the RefreshToken object if valid, None otherwise.
    """
    from finledger.db.models import RefreshToken
    from sqlalchemy import select
    
    # Get all non-revoked, non-expired tokens for user
    result = await db_session.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked == False,
            RefreshToken.expires_at > datetime.now(timezone.utc),
        )
    )
    tokens = result.scalars().all()
    
    # Check each token (constant-time comparison via verify_token)
    for token_obj in tokens:
        if verify_token(refresh_token, token_obj.token_hash):
            return token_obj
    
    return None


async def revoke_refresh_token(
    db_session,
    token_obj: "RefreshToken",
    reason: str = "user_logout",
) -> None:
    """Revoke a refresh token."""
    token_obj.revoked = True
    token_obj.revoked_at = datetime.now(timezone.utc)
    token_obj.revoked_reason = reason
    await db_session.flush()


async def revoke_all_user_tokens(
    db_session,
    user_id: UUID,
    reason: str = "security_event",
) -> int:
    """Revoke all refresh tokens for a user (e.g., on password change)."""
    from finledger.db.models import RefreshToken
    from sqlalchemy import update
    
    result = await db_session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id)
        .where(RefreshToken.revoked == False)
        .values(
            revoked=True,
            revoked_at=datetime.now(timezone.utc),
            revoked_reason=reason,
        )
    )
    return result.rowcount


async def cleanup_expired_tokens(db_session) -> int:
    """Clean up expired/revoked tokens (run as periodic job)."""
    from finledger.db.models import RefreshToken
    from sqlalchemy import delete
    
    result = await db_session.execute(
        delete(RefreshToken).where(
            (RefreshToken.expires_at < datetime.now(timezone.utc)) |
            (RefreshToken.revoked == True)
        )
    )
    return result.rowcount


# Token Blacklist (for logout)
async def add_to_blacklist(redis_client, jti: str, expires_in: int) -> None:
    """Add token JTI to blacklist with TTL."""
    await redis_client.setex(f"blacklist:{jti}", expires_in, "1")


async def is_blacklisted(redis_client, jti: str) -> bool:
    """Check if token JTI is blacklisted."""
    return await redis_client.exists(f"blacklist:{jti}") > 0