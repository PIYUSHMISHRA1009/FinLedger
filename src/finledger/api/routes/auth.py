"""
FinLedger API Routes - Authentication
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header, Request, Response, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from finledger.api.config.settings import get_settings
from finledger.api.schemas import (
    RegisterRequest,
    LoginRequest,
    RefreshRequest,
    LogoutRequest,
    TokenResponse,
    UserResponse,
    ErrorResponse,
)
from finledger.core.auth.rbac import (
    AuthService,
    get_current_user,
    get_current_user_optional,
    AuthenticationError,
    TokenExpiredError,
    TokenRevokedError,
    InvalidCredentialsError,
)
from finledger.core.auth.tokens import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
)
from finledger.db.database import get_db
from finledger.db.models import User

router = APIRouter(prefix="/auth", tags=["Authentication"])
security = HTTPBearer(auto_error=False)


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ErrorResponse, "description": "Validation error"},
        409: {"model": ErrorResponse, "description": "Email already registered"},
    },
)
async def register(
    request: RegisterRequest,
    db: AsyncSession = Depends(get_db),
    user_agent: Optional[str] = Header(None, alias="User-Agent"),
    x_forwarded_for: Optional[str] = Header(None, alias="X-Forwarded-For"),
):
    """
    Register a new user.
    
    Returns access token and refresh token on success.
    """
    auth_service = AuthService(db)
    
    try:
        user = await auth_service.register(
            email=request.email,
            password=request.password,
            full_name=request.full_name,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "VALIDATION_ERROR", "message": str(e)},
        )
    
    # Create token pair
    access_token = create_access_token(
        user_id=user.id,
        email=user.email,
        role=user.role,
    )
    refresh_token = create_refresh_token()
    
    # Store refresh token
    from finledger.core.auth.tokens import store_refresh_token
    from datetime import timedelta
    settings = get_settings()
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    await store_refresh_token(
        db,
        user_id=user.id,
        refresh_token=refresh_token,
        expires_at=expires_at,
        user_agent=user_agent,
        ip_address=x_forwarded_for,
    )
    
    await db.commit()
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Validation error"},
        401: {"model": ErrorResponse, "description": "Invalid credentials"},
        403: {"model": ErrorResponse, "description": "Account locked or deactivated"},
    },
)
async def login(
    request: LoginRequest,
    db: AsyncSession = Depends(get_db),
    user_agent: Optional[str] = Header(None, alias="User-Agent"),
    x_forwarded_for: Optional[str] = Header(None, alias="X-Forwarded-For"),
):
    """
    Authenticate user and return token pair.
    """
    auth_service = AuthService(db)
    
    try:
        user, access_token, refresh_token = await auth_service.login(
            email=request.email,
            password=request.password,
            user_agent=user_agent,
            ip_address=x_forwarded_for,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_CREDENTIALS", "message": str(e)},
        )
    
    settings = get_settings()
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid refresh token"},
        401: {"model": ErrorResponse, "description": "Token expired or revoked"},
    },
)
async def refresh(
    request: RefreshRequest,
    db: AsyncSession = Depends(get_db),
    user_agent: Optional[str] = Header(None, alias="User-Agent"),
    x_forwarded_for: Optional[str] = Header(None, alias="X-Forwarded-For"),
):
    """
    Refresh access token using refresh token.
    
    Implements refresh token rotation (single-use).
    """
    auth_service = AuthService(db)
    
    try:
        access_token, new_refresh_token = await auth_service.refresh(
            refresh_token=request.refresh_token,
            user_agent=user_agent,
            ip_address=x_forwarded_for,
        )
    except ValueError as e:
        error_msg = str(e)
        if "reuse" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "TOKEN_REUSE_DETECTED", "message": "Token reuse detected - all sessions revoked"},
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_REFRESH_TOKEN", "message": error_msg},
        )
    
    settings = get_settings()
    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
    },
)
async def logout(
    request: LogoutRequest,
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer()),
    db: AsyncSession = Depends(get_db),
):
    """
    Logout user by revoking tokens.
    
    Requires both access token (in Authorization header) and refresh token.
    """
    user = await get_current_user(credentials, db)
    auth_service = AuthService(db)
    
    await auth_service.logout(
        user=user,
        refresh_token=request.refresh_token,
        access_token=credentials.credentials,
    )
    
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/me",
    response_model=UserResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
    },
)
async def get_current_user_info(
    user: User = Depends(get_current_user),
):
    """
    Get current authenticated user's profile.
    """
    return UserResponse.model_validate(user)