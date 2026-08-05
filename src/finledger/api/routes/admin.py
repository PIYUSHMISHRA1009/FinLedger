"""
FinLedger Admin Dashboard APIs

Admin/Compliance endpoints for user management, wallet oversight, transaction search,
fraud review queue, and system monitoring.
"""

from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import List, Optional, Dict, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func, and_, or_, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from finledger.api.schemas import (
    AdminUserUpdateRequest,
    AdminStatsResponse,
    FraudEventResponse,
    FraudReviewRequest,
    TransactionResponse,
    WalletResponse,
    UserResponse,
    PaginationParams,
    ErrorResponse,
)
from finledger.api.routes.auth import get_current_user, require_permission, require_role
from finledger.core.auth.tokens import decode_token_unsafe
from finledger.db.database import get_db
from finledger.db.models import (
    User, Wallet, Transaction, FraudEvent, LedgerAccount, AccountBalance,
    WalletStatus, TransactionStatus, FraudEventStatus, UserRole, FraudRiskLevel
)
from finledger.core.fraud.service import FraudService
from finledger.core.ledger.service import LedgerService
from finledger.core.auth.rbac import get_current_user as get_current_user_rbac
from fastapi.security import HTTPBearer

router = APIRouter(prefix="/admin", tags=["Admin Dashboard"])

# =============================================================================
# USER MANAGEMENT
# =============================================================================

@router.get(
    "/users",
    response_model=dict,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Requires admin role"},
    },
)
async def list_users(
    role: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    search: Optional[str] = Query(None, description="Search email or name"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    """List all users with filters (Admin only)."""
    query = select(User)
    
    if role:
        query = query.where(User.role == role)
    if is_active is not None:
        query = query.where(User.is_active == is_active)
    if search:
        search_term = f"%{search}%"
        query = query.where(
            or_(
                User.email.ilike(search_term),
                User.full_name.ilike(search_term),
            )
        )
    
    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query) or 0
    
    # Apply pagination
    query = query.order_by(desc(User.created_at)).limit(limit).offset(offset)
    result = await db.execute(query)
    users = result.scalars().all()
    
    return {
        "items": [UserResponse.model_validate(u) for u in users],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.patch(
    "/users/{user_id}",
    response_model=UserResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Requires admin role"},
        404: {"model": ErrorResponse, "description": "User not found"},
    },
)
async def update_user(
    user_id: UUID,
    request: AdminUserUpdateRequest,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    """Update user role, active status, or verification (Admin only)."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "User not found"},
        )
    
    # Prevent self-demotion
    if user.id == current_user.id and request.role and request.role != "ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Cannot demote yourself"},
        )
    
    if request.role is not None:
        user.role = request.role
    if request.is_active is not None:
        user.is_active = request.is_active
    if request.is_verified is not None:
        user.is_verified = request.is_verified
    
    user.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(user)
    
    return UserResponse.model_validate(user)


@router.delete(
    "/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Requires admin role"},
        404: {"model": ErrorResponse, "description": "User not found"},
        409: {"model": ErrorResponse, "description": "Cannot delete admin user"},
    },
)
async def delete_user(
    user_id: UUID,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    """Delete a user (Admin only)."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "User not found"},
        )
    
    if user.role == UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "FORBIDDEN", "message": "Cannot delete admin user"},
        )
    
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "FORBIDDEN", "message": "Cannot delete yourself"},
        )
    
    await db.delete(user)
    await db.commit()
    return None


# =============================================================================
# WALLET OVERSIGHT
# =============================================================================

@router.get(
    "/wallets",
    response_model=dict,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Requires admin role"},
    },
)
async def list_all_wallets(
    user_id: Optional[UUID] = Query(None),
    currency: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_permission("wallet:manage")),
    db: AsyncSession = Depends(get_db),
):
    """List all wallets across all users (Admin/Compliance)."""
    query = select(Wallet).options(joinedload(Wallet.user))
    
    if user_id:
        query = query.where(Wallet.user_id == user_id)
    if currency:
        query = query.where(Wallet.currency == currency.upper())
    if status:
        query = query.where(Wallet.status == status)
    
    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query) or 0
    
    # Apply pagination
    query = query.order_by(desc(Wallet.created_at)).limit(limit).offset(offset)
    result = await db.execute(query)
    wallets = result.scalars().all()
    
    return {
        "items": [
            {
                **WalletResponse.model_validate(w).model_dump(),
                "user_email": w.user.email if w.user else None,
                "user_name": w.user.full_name if w.user else None,
            }
            for w in wallets
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post(
    "/wallets/{wallet_id}/freeze",
    response_model=WalletResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Requires admin/compliance role"},
        404: {"model": ErrorResponse, "description": "Wallet not found"},
    },
)
async def freeze_wallet(
    wallet_id: UUID,
    current_user: User = Depends(require_permission("wallet:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Freeze a wallet (Admin/Compliance)."""
    result = await db.execute(select(Wallet).where(Wallet.id == wallet_id))
    wallet = result.scalar_one_or_none()
    
    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Wallet not found"},
        )
    
    wallet.status = WalletStatus.FROZEN
    wallet.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(wallet)
    
    return WalletResponse.model_validate(wallet)


@router.post(
    "/wallets/{wallet_id}/unfreeze",
    response_model=WalletResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Requires admin/compliance role"},
        404: {"model": ErrorResponse, "description": "Wallet not found"},
    },
)
async def unfreeze_wallet(
    wallet_id: UUID,
    current_user: User = Depends(require_permission("wallet:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Unfreeze a wallet (Admin/Compliance)."""
    result = await db.execute(select(Wallet).where(Wallet.id == wallet_id))
    wallet = result.scalar_one_or_none()
    
    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Wallet not found"},
        )
    
    wallet.status = WalletStatus.ACTIVE
    wallet.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(wallet)
    
    return WalletResponse.model_validate(wallet)


# =============================================================================
# TRANSACTION SEARCH
# =============================================================================

@router.get(
    "/transactions",
    response_model=dict,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Requires admin/compliance role"},
    },
)
async def search_transactions(
    user_id: Optional[UUID] = Query(None),
    wallet_id: Optional[UUID] = Query(None),
    type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    min_amount: Optional[Decimal] = Query(None),
    max_amount: Optional[Decimal] = Query(None),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_permission("transaction:read_all")),
    db: AsyncSession = Depends(get_db),
):
    """Search all transactions across all users (Admin/Compliance)."""
    query = select(Transaction)
    
    if user_id:
        query = query.where(
            or_(
                Transaction.source_wallet_id.in_(
                    select(Wallet.id).where(Wallet.user_id == user_id)
                ),
                Transaction.destination_wallet_id.in_(
                    select(Wallet.id).where(Wallet.user_id == user_id)
                ),
            )
        )
    if wallet_id:
        query = query.where(
            or_(
                Transaction.source_wallet_id == wallet_id,
                Transaction.destination_wallet_id == wallet_id,
            )
        )
    if type:
        query = query.where(Transaction.type == type)
    if status:
        query = query.where(Transaction.status == status)
    if min_amount is not None:
        query = query.where(Transaction.amount >= min_amount)
    if max_amount is not None:
        query = query.where(Transaction.amount <= max_amount)
    if start_date:
        query = query.where(Transaction.created_at >= start_date)
    if end_date:
        query = query.where(Transaction.created_at <= end_date)
    
    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query) or 0
    
    # Apply pagination
    query = query.order_by(desc(Transaction.created_at)).limit(limit).offset(offset)
    result = await db.execute(query)
    transactions = result.scalars().all()
    
    return {
        "items": [TransactionResponse.model_validate(t) for t in transactions],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


# =============================================================================
# FRAUD REVIEW QUEUE
# =============================================================================

@router.get(
    "/fraud/events",
    response_model=dict,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Requires compliance/admin role"},
    },
)
async def list_fraud_events(
    risk_level: Optional[FraudRiskLevel] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_permission("fraud:read")),
    db: AsyncSession = Depends(get_db),
):
    """List fraud events for review (Compliance/Admin)."""
    fraud_service = FraudService(db)
    events, total = await fraud_service.get_fraud_events(
        risk_level=risk_level,
        status=status,
        limit=limit,
        offset=offset,
    )
    
    return {
        "items": [FraudEventResponse.model_validate(e) for e in events],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.patch(
    "/fraud/events/{event_id}/review",
    response_model=FraudEventResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Requires compliance role"},
        404: {"model": ErrorResponse, "description": "Fraud event not found"},
    },
)
async def review_fraud_event(
    event_id: UUID,
    request: FraudReviewRequest,
    current_user: User = Depends(require_role("COMPLIANCE", "ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    """Review a fraud event (Compliance/Admin)."""
    fraud_service = FraudService(db)
    
    try:
        event = await fraud_service.review_fraud_event(
            event_id=event_id,
            reviewer_id=current_user.id,
            status=request.status,
            notes=request.review_notes,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": str(e)},
        )
    
    return FraudEventResponse.model_validate(event)


# =============================================================================
# SYSTEM STATS & MONITORING
# =============================================================================

@router.get(
    "/stats",
    response_model=AdminStatsResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Requires admin role"},
    },
)
async def get_admin_stats(
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    """Get system-wide statistics (Admin only)."""
    # Total users
    total_users = await db.scalar(select(func.count(User.id))) or 0
    
    # Active users (logged in last 30 days)
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    active_users = await db.scalar(
        select(func.count(User.id)).where(User.last_login_at >= cutoff)
    ) or 0
    
    # Total wallets
    total_wallets = await db.scalar(select(func.count(Wallet.id))) or 0
    
    # Active wallets
    active_wallets = await db.scalar(
        select(func.count(Wallet.id)).where(Wallet.status == WalletStatus.ACTIVE)
    ) or 0
    
    # Total transactions (all time)
    total_transactions = await db.scalar(
        select(func.count(Transaction.id))
    ) or 0
    
    # Transaction volume (last 24h)
    day_ago = datetime.now(timezone.utc) - timedelta(days=1)
    recent_volume = await db.scalar(
        select(func.coalesce(func.sum(Transaction.amount), Decimal("0")))
        .where(Transaction.created_at >= day_ago)
        .where(Transaction.status == TransactionStatus.COMPLETED)
    ) or Decimal("0")
    
    # Pending fraud reviews
    pending_fraud = await db.scalar(
        select(func.count(FraudEvent.id))
        .where(FraudEvent.status == FraudEventStatus.PENDING_REVIEW)
    ) or 0
    
    return AdminStatsResponse(
        total_users=total_users,
        active_users=active_users,
        total_wallets=total_wallets,
        active_wallets=active_wallets,
        total_transactions=total_transactions,
        total_volume=str(recent_volume),
        pending_fraud_reviews=pending_fraud,
    )


# =============================================================================
# LEDGER MONITORING
# =============================================================================

@router.get(
    "/ledger/trial-balance",
    response_model=dict,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Requires admin/compliance role"},
    },
)
async def get_trial_balance_admin(
    as_of: Optional[datetime] = Query(None),
    current_user: User = Depends(require_permission("ledger:read")),
    db: AsyncSession = Depends(get_db),
):
    """Get trial balance (Admin/Compliance)."""
    ledger_service = LedgerService(db)
    trial_balance = await ledger_service.get_trial_balance(as_of=as_of)
    return trial_balance


@router.get(
    "/ledger/accounts",
    response_model=dict,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Requires admin/compliance role"},
    },
)
async def list_ledger_accounts(
    account_type: Optional[str] = Query(None),
    active_only: bool = Query(True),
    current_user: User = Depends(require_permission("ledger:read")),
    db: AsyncSession = Depends(get_db),
):
    """List all ledger accounts (Chart of Accounts)."""
    query = select(LedgerAccount)
    
    if account_type:
        query = query.where(LedgerAccount.account_type == account_type)
    if active_only:
        query = query.where(LedgerAccount.is_active == True)
    
    query = query.order_by(LedgerAccount.code)
    result = await db.execute(query)
    accounts = result.scalars().all()
    
    return {
        "items": [
            {
                "id": str(a.id),
                "code": a.code,
                "name": a.name,
                "account_type": a.account_type.value,
                "normality": a.normality.value,
                "currency": a.currency,
                "is_active": a.is_active,
                "is_system_account": a.is_system_account,
            }
            for a in accounts
        ],
        "total": len(accounts),
    }