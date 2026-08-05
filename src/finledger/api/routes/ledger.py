"""
FinLedger API Routes - Ledger
"""

from typing import Optional, List
from uuid import UUID
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from finledger.api.schemas import (
    LedgerAccountResponse,
    LedgerTransactionResponse,
    LedgerTransactionListParams,
    AccountBalanceResponse,
    TrialBalanceResponse,
    ErrorResponse,
)
from finledger.api.routes.auth import get_current_user, require_permission
from finledger.core.ledger.service import LedgerService
from finledger.core.ledger.exceptions import AccountNotFoundError
from finledger.db.database import get_db
from finledger.db.models import User

router = APIRouter(prefix="/ledger", tags=["Ledger"])
security = HTTPBearer(auto_error=False)


def get_ledger_service(
    db: AsyncSession = Depends(get_db),
) -> LedgerService:
    """Dependency for ledger service."""
    return LedgerService(db)


@router.get(
    "/accounts",
    response_model=dict,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
    },
)
async def list_ledger_accounts(
    account_type: Optional[str] = Query(None),
    active_only: bool = Query(True),
    current_user: User = Depends(get_current_user),
    ledger_service: LedgerService = Depends(get_ledger_service),
):
    """
    List ledger accounts (Chart of Accounts).
    """
    # Filter by type if provided
    # This would need a service method; for now return all
    from finledger.db.models import LedgerAccount
    from sqlalchemy import select
    from finledger.db.database import get_db
    
    # This is a simplified version - in production use service layer
    return {
        "items": [],
        "total": 0,
        "limit": 20,
        "offset": 0,
    }


@router.get(
    "/accounts/{account_code}",
    response_model=LedgerAccountResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Account not found"},
    },
)
async def get_ledger_account(
    account_code: str,
    current_user: User = Depends(get_current_user),
    ledger_service: LedgerService = Depends(get_ledger_service),
):
    """
    Get ledger account by code.
    """
    try:
        account = await ledger_service.get_account_by_code(account_code)
    except AccountNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": str(e)},
        )
    
    return LedgerAccountResponse.model_validate(account)


@router.get(
    "/transactions",
    response_model=dict,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
    },
)
async def list_ledger_transactions(
    params: LedgerTransactionListParams = Depends(),
    current_user: User = Depends(get_current_user),
    ledger_service: LedgerService = Depends(get_ledger_service),
):
    """
    List ledger transactions with filters and pagination.
    """
    # This would use a service method to query ledger transactions
    # For now return empty
    return {
        "items": [],
        "total": 0,
        "limit": params.limit,
        "offset": params.offset,
    }


@router.get(
    "/transactions/{transaction_id}",
    response_model=LedgerTransactionResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Transaction not found"},
    },
)
async def get_ledger_transaction(
    transaction_id: UUID,
    current_user: User = Depends(get_current_user),
    ledger_service: LedgerService = Depends(get_ledger_service),
):
    """
    Get ledger transaction with all entries.
    """
    # Would query by ID
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Not yet implemented",
    )


@router.get(
    "/accounts/{account_code}/balance",
    response_model=AccountBalanceResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Account not found"},
    },
)
async def get_account_balance(
    account_code: str,
    wallet_id: Optional[UUID] = Query(None),
    as_of: Optional[datetime] = Query(None),
    current_user: User = Depends(get_current_user),
    ledger_service: LedgerService = Depends(get_ledger_service),
):
    """
    Get account balance at a point in time.
    """
    try:
        balance = await ledger_service.get_balance(
            account_code=account_code,
            wallet_id=wallet_id,
            as_of=as_of,
        )
    except AccountNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": str(e)},
        )
    
    return AccountBalanceResponse(
        account_id=UUID("00000000-0000-0000-0000-000000000000"),  # Would be actual ID
        account_code=account_code,
        wallet_id=wallet_id,
        posted_balance=str(balance.posted),
        pending_balance=str(balance.pending),
        available_balance=str(balance.available),
        as_of=balance.as_of,
    )


@router.get(
    "/trial-balance",
    response_model=TrialBalanceResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Requires admin/compliance role"},
    },
)
async def get_trial_balance(
    as_of: Optional[datetime] = Query(None),
    current_user: User = Depends(require_permission("ledger:read")),
    ledger_service: LedgerService = Depends(get_ledger_service),
):
    """
    Get trial balance (all accounts with net balances).
    
    Requires ledger:read permission (ADMIN, COMPLIANCE, SYSTEM).
    """
    trial_balance = await ledger_service.get_trial_balance(as_of=as_of)
    
    return TrialBalanceResponse(
        as_of=datetime.fromisoformat(trial_balance["as_of"]),
        accounts=trial_balance["accounts"],
        total_debits=trial_balance["total_debits"],
        total_credits=trial_balance["total_credits"],
        balanced=trial_balance["balanced"],
    )