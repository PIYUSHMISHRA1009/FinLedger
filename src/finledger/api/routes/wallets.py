"""
FinLedger API Routes - Wallets
"""

from decimal import Decimal
from typing import Optional, List
from uuid import UUID
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Header, Query, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from finledger.api.schemas import (
    WalletCreateRequest,
    WalletUpdateRequest,
    WalletResponse,
    WalletBalanceResponse,
    DepositRequest,
    WithdrawalRequest,
    TransferRequest,
    TransactionResponse,
    PaginationParams,
    ErrorResponse,
)
from finledger.api.routes.auth import get_current_user
from finledger.core.wallet.service import WalletService
from finledger.core.ledger.service import LedgerService
from finledger.core.fraud.service import FraudService
from finledger.core.exceptions import (
    WalletNotFoundError,
    WalletFrozenError,
    WalletClosedError,
    InsufficientFundsError,
    CurrencyMismatchError,
    SameWalletTransferError,
    ValidationError,
)
from finledger.db.database import get_db
from finledger.db.models import User, Transaction

router = APIRouter(prefix="/wallets", tags=["Wallets"])
security = HTTPBearer(auto_error=False)


def get_wallet_service(
    db: AsyncSession = Depends(get_db),
) -> WalletService:
    """Dependency for wallet service."""
    ledger_service = LedgerService(db)
    fraud_service = FraudService(db)
    return WalletService(db, ledger_service, fraud_service)


@router.post(
    "",
    response_model=WalletResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ErrorResponse, "description": "Validation error"},
        409: {"model": ErrorResponse, "description": "Wallet already exists"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
    },
)
async def create_wallet(
    request: WalletCreateRequest,
    current_user: User = Depends(get_current_user),
    wallet_service: WalletService = Depends(get_wallet_service),
):
    """
    Create a new wallet for the authenticated user.
    """
    try:
        wallet = await wallet_service.create_wallet(
            user_id=current_user.id,
            currency=request.currency,
            name=request.name,
        )
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "VALIDATION_ERROR", "message": str(e)},
        )
    
    return WalletResponse.model_validate(wallet)


@router.get(
    "",
    response_model=dict,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
    },
)
async def list_wallets(
    currency: Optional[str] = Query(None, min_length=3, max_length=3),
    status: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    wallet_service: WalletService = Depends(get_wallet_service),
):
    """
    List wallets for the authenticated user with pagination.
    """
    wallets, total = await wallet_service.list_wallets(
        user_id=current_user.id,
        currency=currency,
        status=status,
        limit=limit,
        offset=offset,
    )
    
    return {
        "items": [WalletResponse.model_validate(w) for w in wallets],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get(
    "/{wallet_id}",
    response_model=WalletResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Wallet not found"},
    },
)
async def get_wallet(
    wallet_id: UUID,
    current_user: User = Depends(get_current_user),
    wallet_service: WalletService = Depends(get_wallet_service),
):
    """
    Get a specific wallet by ID.
    """
    try:
        wallet = await wallet_service.get_wallet(wallet_id, current_user.id)
    except WalletNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": str(e)},
        )
    
    return WalletResponse.model_validate(wallet)


@router.get(
    "/{wallet_id}/balance",
    response_model=WalletBalanceResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Wallet not found"},
    },
)
async def get_wallet_balance(
    wallet_id: UUID,
    current_user: User = Depends(get_current_user),
    wallet_service: WalletService = Depends(get_wallet_service),
):
    """
    Get wallet balance (Posted, Pending, Available).
    """
    try:
        balance = await wallet_service.get_balance(wallet_id)
    except WalletNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": str(e)},
        )
    
    return WalletBalanceResponse(
        wallet_id=balance.wallet_id,
        currency=balance.currency,
        posted_balance=str(balance.posted_balance),
        pending_balance=str(balance.pending_balance),
        available_balance=str(balance.available_balance),
        as_of=balance.as_of,
    )


@router.post(
    "/{wallet_id}/deposit",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ErrorResponse, "description": "Validation error"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Wallet not found"},
        409: {"model": ErrorResponse, "description": "Idempotency key conflict"},
    },
)
async def deposit(
    wallet_id: UUID,
    request: DepositRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    wallet_service: WalletService = Depends(get_wallet_service),
):
    """
    Deposit funds into wallet.
    
    Requires Idempotency-Key header for exactly-once semantics.
    """
    try:
        result = await wallet_service.deposit(
            wallet_id=wallet_id,
            amount=request.amount,
            description=request.description,
            metadata=request.metadata,
            idempotency_key=idempotency_key,
        )
    except WalletNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": str(e)},
        )
    except WalletFrozenError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "WALLET_FROZEN", "message": str(e)},
        )
    except WalletClosedError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "WALLET_CLOSED", "message": str(e)},
        )
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "VALIDATION_ERROR", "message": str(e)},
        )
    
    return TransactionResponse(
        id=result.transaction_id,
        type="DEPOSIT",
        status=result.status,
        amount=str(result.amount),
        currency=result.currency,
        description=request.description,
        destination_wallet_id=wallet_id,
        posted_balance=str(result.posted_balance),
        available_balance=str(result.available_balance),
        fraud_risk_score=result.fraud_risk_score,
        fraud_risk_level=result.fraud_risk_level,
        created_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
    )


@router.post(
    "/{wallet_id}/withdraw",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ErrorResponse, "description": "Validation error"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Wallet not found"},
        409: {"model": ErrorResponse, "description": "Insufficient funds / Wallet frozen / Idempotency conflict"},
    },
)
async def withdraw(
    wallet_id: UUID,
    request: WithdrawalRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    wallet_service: WalletService = Depends(get_wallet_service),
):
    """
    Withdraw funds from wallet.
    
    Requires Idempotency-Key header for exactly-once semantics.
    """
    try:
        result = await wallet_service.withdraw(
            wallet_id=wallet_id,
            amount=request.amount,
            description=request.description,
            metadata=request.metadata,
            idempotency_key=idempotency_key,
        )
    except WalletNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": str(e)},
        )
    except WalletFrozenError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "WALLET_FROZEN", "message": str(e)},
        )
    except WalletClosedError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "WALLET_CLOSED", "message": str(e)},
        )
    except InsufficientFundsError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "INSUFFICIENT_FUNDS", "message": str(e)},
        )
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "VALIDATION_ERROR", "message": str(e)},
        )
    
    return TransactionResponse(
        id=result.transaction_id,
        type="WITHDRAWAL",
        status=result.status,
        amount=str(result.amount),
        currency=result.currency,
        description=request.description,
        source_wallet_id=wallet_id,
        posted_balance=str(result.posted_balance),
        available_balance=str(result.available_balance),
        created_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
    )


@router.post(
    "/{wallet_id}/transfer",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ErrorResponse, "description": "Validation error"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Wallet not found"},
        409: {"model": ErrorResponse, "description": "Insufficient funds / Currency mismatch / Same wallet / Idempotency conflict"},
    },
)
async def transfer(
    wallet_id: UUID,
    request: TransferRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    wallet_service: WalletService = Depends(get_wallet_service),
):
    """
    Transfer funds to another wallet.
    
    Requires Idempotency-Key header for exactly-once semantics.
    """
    try:
        source_result, dest_result = await wallet_service.transfer(
            source_wallet_id=wallet_id,
            destination_wallet_id=request.destination_wallet_id,
            amount=request.amount,
            description=request.description,
            metadata=request.metadata,
            idempotency_key=idempotency_key,
        )
    except WalletNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": str(e)},
        )
    except WalletFrozenError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "WALLET_FROZEN", "message": str(e)},
        )
    except WalletClosedError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "WALLET_CLOSED", "message": str(e)},
        )
    except InsufficientFundsError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "INSUFFICIENT_FUNDS", "message": str(e)},
        )
    except CurrencyMismatchError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "CURRENCY_MISMATCH", "message": str(e)},
        )
    except SameWalletTransferError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "SAME_WALLET_TRANSFER", "message": str(e)},
        )
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "VALIDATION_ERROR", "message": str(e)},
        )
    
    # Return source transaction (TRANSFER_OUT)
    return TransactionResponse(
        id=source_result.transaction_id,
        type="TRANSFER_OUT",
        status=source_result.status,
        amount=str(source_result.amount),
        currency=source_result.currency,
        description=request.description,
        source_wallet_id=wallet_id,
        destination_wallet_id=request.destination_wallet_id,
        posted_balance=str(source_result.posted_balance),
        available_balance=str(source_result.available_balance),
        fraud_risk_score=source_result.fraud_risk_score,
        fraud_risk_level=source_result.fraud_risk_level,
        created_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
    )


@router.get(
    "/{wallet_id}/transactions",
    response_model=dict,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Wallet not found"},
    },
)
async def get_wallet_transactions(
    wallet_id: UUID,
    type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    current_user: User = Depends(get_current_user),
    wallet_service: WalletService = Depends(get_wallet_service),
):
    """
    Get transactions for a wallet with filters and pagination.
    """
    try:
        transactions, total = await wallet_service.get_transactions(
            wallet_id=wallet_id,
            type=type,
            status=status,
            limit=limit,
            offset=offset,
            start_date=start_date,
            end_date=end_date,
        )
    except WalletNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": str(e)},
        )
    
    # Enhance transactions with counterparty info
    from finledger.db.database import get_db
    from sqlalchemy import select
    from finledger.db.models import Wallet, User
    
    # This would ideally be done in the service layer with joins
    # For now, return basic transaction info
    
    return {
        "items": [
            TransactionResponse(
                id=txn.id,
                type=txn.type,
                status=txn.status,
                amount=str(txn.amount),
                currency=txn.currency,
                description=txn.description,
                source_wallet_id=txn.source_wallet_id,
                destination_wallet_id=txn.destination_wallet_id,
                created_at=txn.created_at,
                completed_at=txn.completed_at,
            )
            for txn in transactions
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }