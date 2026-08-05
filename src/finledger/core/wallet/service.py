"""
FinLedger Wallet Service

Manages wallet operations: CRUD, deposits, withdrawals, transfers.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import List, Optional, Tuple
from uuid import UUID
from datetime import datetime, timezone

from sqlalchemy import select, func, update, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from finledger.db.models import (
    Wallet,
    Transaction,
    AccountBalance,
    LedgerAccount,
    TransactionType,
    TransactionStatus,
    WalletStatus,
)
from finledger.core.ledger.service import LedgerService, LedgerEntrySpec, LedgerEntryType
from finledger.core.ledger.exceptions import (
    InsufficientBalanceError,
    AccountNotFoundError,
)
from finledger.core.exceptions import (
    WalletNotFoundError,
    WalletFrozenError,
    WalletClosedError,
    InsufficientFundsError,
    CurrencyMismatchError,
    SameWalletTransferError,
    ValidationError,
)
from finledger.core.fraud.service import FraudService, FraudAssessment


@dataclass
class WalletBalance:
    """Wallet balance information."""
    wallet_id: UUID
    currency: str
    posted_balance: Decimal
    pending_balance: Decimal
    available_balance: Decimal
    as_of: datetime


@dataclass
class TransferResult:
    """Result of a transfer operation."""
    transaction_id: UUID
    status: TransactionStatus
    amount: Decimal
    currency: str
    posted_balance: Decimal
    available_balance: Decimal
    fraud_risk_score: Optional[str] = None
    fraud_risk_level: Optional[str] = None


class WalletService:
    """Service for wallet operations."""
    
    def __init__(self, db: AsyncSession, ledger_service: LedgerService, fraud_service: "FraudService"):
        self.db = db
        self.ledger = ledger_service
        self.fraud = fraud_service
    
    async def create_wallet(
        self,
        user_id: UUID,
        currency: str,
        name: str,
    ) -> Wallet:
        """Create a new wallet for a user."""
        # Validate currency
        if len(currency) != 3:
            raise ValidationError("Currency must be 3 characters (ISO 4217)")
        
        # Check for existing wallet with same name/currency
        existing = await self.db.execute(
            select(Wallet).where(
                Wallet.user_id == user_id,
                Wallet.currency == currency,
                Wallet.name == name,
                Wallet.status.in_([WalletStatus.ACTIVE, WalletStatus.PENDING_VERIFICATION]),
            )
        )
        if existing.scalar_one_or_none():
            raise ValidationError(f"Wallet with name '{name}' and currency '{currency}' already exists")
        
        wallet = Wallet(
            user_id=user_id,
            currency=currency.upper(),
            name=name,
            status=WalletStatus.ACTIVE,
        )
        
        self.db.add(wallet)
        await self.db.flush()
        await self.db.refresh(wallet)
        
        return wallet
    
    async def get_wallet(self, wallet_id: UUID, user_id: Optional[UUID] = None) -> Wallet:
        """Get wallet by ID, optionally filtered by user."""
        query = select(Wallet).where(Wallet.id == wallet_id)
        if user_id:
            query = query.where(Wallet.user_id == user_id)
        
        result = await self.db.execute(query)
        wallet = result.scalar_one_or_none()
        
        if not wallet:
            raise WalletNotFoundError(f"Wallet not found: {wallet_id}")
        
        return wallet
    
    async def list_wallets(
        self,
        user_id: UUID,
        currency: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Tuple[List[Wallet], int]:
        """List wallets for a user with pagination."""
        query = select(Wallet).where(Wallet.user_id == user_id)
        
        if currency:
            query = query.where(Wallet.currency == currency.upper())
        if status:
            query = query.where(Wallet.status == status)
        
        # Count total
        count_query = select(func.count()).select_from(query.subquery())
        total = await self.db.scalar(count_query) or 0
        
        # Apply pagination
        query = query.order_by(Wallet.created_at.desc()).limit(limit).offset(offset)
        result = await self.db.execute(query)
        wallets = result.scalars().all()
        
        return wallets, total
    
    async def get_balance(self, wallet_id: UUID) -> WalletBalance:
        """Get wallet balance (Posted, Pending, Available)."""
        wallet = await self.get_wallet(wallet_id)
        
        # Get liability account for this currency
        liability_account_code = f"201{wallet.currency[-1]}"  # 2010, 2011, 2012
        
        # Get balance from ledger service
        balance = await self.ledger.get_balance(
            account_code=liability_account_code,
            wallet_id=wallet_id,
        )
        
        # For liabilities, negative balance = customer funds (positive from user perspective)
        return WalletBalance(
            wallet_id=wallet_id,
            currency=wallet.currency,
            posted_balance=-balance.posted,
            pending_balance=-balance.pending,
            available_balance=-balance.available,
            as_of=balance.as_of,
        )
    
    async def _lock_wallet(self, wallet_id: UUID) -> Wallet:
        """Lock wallet for update (SELECT FOR UPDATE)."""
        result = await self.db.execute(
            select(Wallet).where(Wallet.id == wallet_id).with_for_update()
        )
        wallet = result.scalar_one_or_none()
        if not wallet:
            raise WalletNotFoundError(f"Wallet not found: {wallet_id}")
        return wallet
    
    async def _validate_wallet_for_transaction(
        self,
        wallet: Wallet,
        required_status: WalletStatus = WalletStatus.ACTIVE,
    ) -> None:
        """Validate wallet can be used for transaction."""
        if wallet.status == WalletStatus.FROZEN:
            raise WalletFrozenError(f"Wallet {wallet.id} is frozen")
        if wallet.status == WalletStatus.CLOSED:
            raise WalletClosedError(f"Wallet {wallet.id} is closed")
        if wallet.status != required_status:
            raise ValidationError(f"Wallet status must be {required_status.value}")
    
    async def deposit(
        self,
        wallet_id: UUID,
        amount: Decimal,
        description: str,
        metadata: Optional[dict] = None,
        idempotency_key: Optional[str] = None,
    ) -> TransferResult:
        """
        Deposit funds into wallet (external source).
        
        Creates ledger entries:
        - DEBIT: Settlement Account (1030)
        - CREDIT: Customer Liability (2010/2011/2012)
        """
        wallet = await self._lock_wallet(wallet_id)
        await self._validate_wallet_for_transaction(wallet)
        
        # Get accounts
        settlement_account = await self.ledger.get_account_by_code("1030")
        liability_account = await self.ledger.get_account_by_code(f"201{wallet.currency[-1]}")
        
        # Create ledger entries
        entries = [
            LedgerEntrySpec(
                account_code=settlement_account.code,
                entry_type=LedgerEntryType.DEBIT,
                amount=amount,
                description=f"Deposit to {wallet.name}: {description}",
                wallet_id=wallet_id,
            ),
            LedgerEntrySpec(
                account_code=liability_account.code,
                entry_type=LedgerEntryType.CREDIT,
                amount=amount,
                description=f"Deposit to {wallet.name}: {description}",
                wallet_id=wallet_id,
            ),
        ]
        
        # Create ledger transaction
        reference = f"DEP-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{wallet_id.hex[:8]}"
        ledger_txn = await self.ledger.create_transaction(
            reference=reference,
            description=f"Deposit to wallet {wallet.name}: {description}",
            entries=entries,
            metadata=metadata or {"wallet_id": str(wallet_id), "type": "deposit"},
        )
        
        # Create business transaction record
        txn = Transaction(
            source_wallet_id=None,
            destination_wallet_id=wallet_id,
            ledger_transaction_id=ledger_txn.id,
            type=TransactionType.DEPOSIT,
            status=TransactionStatus.COMPLETED,
            amount=amount,
            currency=wallet.currency,
            description=description,
            idempotency_key=idempotency_key or f"dep-{wallet_id}-{amount}",
            metadata=metadata or {},
            completed_at=datetime.now(timezone.utc),
        )
        
        self.db.add(txn)
        await self.db.commit()
        await self.db.refresh(txn)
        
        # Get updated balance
        balance = await self.get_balance(wallet_id)
        
        return TransferResult(
            transaction_id=txn.id,
            status=TransactionStatus.COMPLETED,
            amount=amount,
            currency=wallet.currency,
            posted_balance=balance.posted_balance,
            available_balance=balance.available_balance,
        )
    
    async def withdraw(
        self,
        wallet_id: UUID,
        amount: Decimal,
        description: str,
        metadata: Optional[dict] = None,
        idempotency_key: Optional[str] = None,
    ) -> TransferResult:
        """
        Withdraw funds from wallet (to external destination).
        
        Validates available balance.
        Creates ledger entries:
        - DEBIT: Customer Liability (2010/2011/2012)
        - CREDIT: Settlement Account (1030)
        """
        wallet = await self._lock_wallet(wallet_id)
        await self._validate_wallet_for_transaction(wallet)
        
        # Check available balance
        balance = await self.get_balance(wallet_id)
        if balance.available_balance < amount:
            raise InsufficientFundsError(
                f"Available balance {balance.available_balance} < requested {amount}"
            )
        
        # Get accounts
        settlement_account = await self.ledger.get_account_by_code("1030")
        liability_account = await self.ledger.get_account_by_code(f"201{wallet.currency[-1]}")
        
        # Create ledger entries
        entries = [
            LedgerEntrySpec(
                account_code=liability_account.code,
                entry_type=LedgerEntryType.DEBIT,
                amount=amount,
                description=f"Withdrawal from {wallet.name}: {description}",
                wallet_id=wallet_id,
            ),
            LedgerEntrySpec(
                account_code=settlement_account.code,
                entry_type=LedgerEntryType.CREDIT,
                amount=amount,
                description=f"Withdrawal from {wallet.name}: {description}",
                wallet_id=wallet_id,
            ),
        ]
        
        # Create ledger transaction
        reference = f"WDR-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{wallet_id.hex[:8]}"
        ledger_txn = await self.ledger.create_transaction(
            reference=reference,
            description=f"Withdrawal from wallet {wallet.name}: {description}",
            entries=entries,
            metadata=metadata or {"wallet_id": str(wallet_id), "type": "withdrawal"},
        )
        
        # Create business transaction record
        txn = Transaction(
            source_wallet_id=wallet_id,
            destination_wallet_id=None,
            ledger_transaction_id=ledger_txn.id,
            type=TransactionType.WITHDRAWAL,
            status=TransactionStatus.COMPLETED,
            amount=amount,
            currency=wallet.currency,
            description=description,
            idempotency_key=idempotency_key or f"wdr-{wallet_id}-{amount}",
            metadata=metadata or {},
            completed_at=datetime.now(timezone.utc),
        )
        
        self.db.add(txn)
        await self.db.commit()
        await self.db.refresh(txn)
        
        # Get updated balance
        balance = await self.get_balance(wallet_id)
        
        return TransferResult(
            transaction_id=txn.id,
            status=TransactionStatus.COMPLETED,
            amount=amount,
            currency=wallet.currency,
            posted_balance=balance.posted_balance,
            available_balance=balance.available_balance,
        )
    
    async def transfer(
        self,
        source_wallet_id: UUID,
        destination_wallet_id: UUID,
        amount: Decimal,
        description: str,
        metadata: Optional[dict] = None,
        idempotency_key: Optional[str] = None,
    ) -> Tuple[TransferResult, TransferResult]:
        """
        Transfer between wallets.
        
        Validates:
        - Source wallet has sufficient available balance
        - Same currency
        - Not transferring to self
        - Wallets are active
        
        Creates ledger entries:
        - DEBIT: Source Customer Liability
        - CREDIT: Destination Customer Liability
        """
        # Lock both wallets in consistent order (by UUID) to prevent deadlocks
        wallet_ids = sorted([source_wallet_id, destination_wallet_id])
        
        source_wallet = await self._lock_wallet(source_wallet_id)
        dest_wallet = await self._lock_wallet(destination_wallet_id)
        
        # Validate
        await self._validate_wallet_for_transaction(source_wallet)
        await self._validate_wallet_for_transaction(dest_wallet)
        
        if source_wallet_id == destination_wallet_id:
            raise SameWalletTransferError("Cannot transfer to same wallet")
        
        if source_wallet.currency != dest_wallet.currency:
            raise CurrencyMismatchError(
                f"Currency mismatch: {source_wallet.currency} != {dest_wallet.currency}"
            )
        
        # Check available balance
        balance = await self.get_balance(source_wallet_id)
        if balance.available_balance < amount:
            raise InsufficientFundsError(
                f"Available balance {balance.available_balance} < requested {amount}"
            )
        
        # Get liability account for this currency
        liability_account = await self.ledger.get_account_by_code(f"201{source_wallet.currency[-1]}")
        
        # Create ledger entries
        entries = [
            LedgerEntrySpec(
                account_code=liability_account.code,
                entry_type=LedgerEntryType.DEBIT,
                amount=amount,
                description=f"Transfer from {source_wallet.name} to {dest_wallet.name}: {description}",
                wallet_id=source_wallet_id,
            ),
            LedgerEntrySpec(
                account_code=liability_account.code,
                entry_type=LedgerEntryType.CREDIT,
                amount=amount,
                description=f"Transfer from {source_wallet.name} to {dest_wallet.name}: {description}",
                wallet_id=destination_wallet_id,
            ),
        ]
        
        # Create ledger transaction
        reference = f"XFR-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{source_wallet_id.hex[:8]}"
        ledger_txn = await self.ledger.create_transaction(
            reference=reference,
            description=f"Transfer {source_wallet.name} -> {dest_wallet.name}: {description}",
            entries=entries,
            metadata=metadata or {
                "source_wallet_id": str(source_wallet_id),
                "dest_wallet_id": str(destination_wallet_id),
                "type": "transfer",
            },
        )
        
        # Run fraud check asynchronously
        fraud_assessment = await self.fraud.evaluate_transaction(
            transaction_id=ledger_txn.id,
            source_wallet_id=source_wallet_id,
            destination_wallet_id=destination_wallet_id,
            amount=amount,
            currency=source_wallet.currency,
        )
        
        # Create business transaction records
        # Source: TRANSFER_OUT
        source_txn = Transaction(
            source_wallet_id=source_wallet_id,
            destination_wallet_id=destination_wallet_id,
            ledger_transaction_id=ledger_txn.id,
            type=TransactionType.TRANSFER_OUT,
            status=TransactionStatus.COMPLETED,
            amount=amount,
            currency=source_wallet.currency,
            description=description,
            idempotency_key=idempotency_key or f"xfr-{source_wallet_id}-{amount}",
            metadata=metadata or {},
            completed_at=datetime.now(timezone.utc),
        )
        
        # Destination: TRANSFER_IN
        dest_txn = Transaction(
            source_wallet_id=source_wallet_id,
            destination_wallet_id=destination_wallet_id,
            ledger_transaction_id=ledger_txn.id,
            type=TransactionType.TRANSFER_IN,
            status=TransactionStatus.COMPLETED,
            amount=amount,
            currency=dest_wallet.currency,
            description=description,
            idempotency_key=f"{idempotency_key or 'xfr'}-in-{dest_wallet_id}",
            metadata=metadata or {},
            completed_at=datetime.now(timezone.utc),
        )
        
        self.db.add_all([source_txn, dest_txn])
        await self.db.commit()
        await self.db.refresh(source_txn)
        await self.db.refresh(dest_txn)
        
        # Get updated balances
        source_balance = await self.get_balance(source_wallet_id)
        dest_balance = await self.get_balance(destination_wallet_id)
        
        return (
            TransferResult(
                transaction_id=source_txn.id,
                status=TransactionStatus.COMPLETED,
                amount=amount,
                currency=source_wallet.currency,
                posted_balance=source_balance.posted_balance,
                available_balance=source_balance.available_balance,
                fraud_risk_score=str(fraud_assessment.risk_score) if fraud_assessment else None,
                fraud_risk_level=fraud_assessment.risk_level.value if fraud_assessment else None,
            ),
            TransferResult(
                transaction_id=dest_txn.id,
                status=TransactionStatus.COMPLETED,
                amount=amount,
                currency=dest_wallet.currency,
                posted_balance=dest_balance.posted_balance,
                available_balance=dest_balance.available_balance,
            ),
        )
    
    async def get_transactions(
        self,
        wallet_id: UUID,
        type: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Tuple[List[Transaction], int]:
        """Get transactions for a wallet with filters."""
        query = select(Transaction).where(
            or_(
                Transaction.source_wallet_id == wallet_id,
                Transaction.destination_wallet_id == wallet_id,
            )
        )
        
        if type:
            query = query.where(Transaction.type == type)
        if status:
            query = query.where(Transaction.status == status)
        if start_date:
            query = query.where(Transaction.created_at >= start_date)
        if end_date:
            query = query.where(Transaction.created_at <= end_date)
        
        # Count total
        count_query = select(func.count()).select_from(query.subquery())
        total = await self.db.scalar(count_query) or 0
        
        # Apply pagination
        query = query.order_by(Transaction.created_at.desc()).limit(limit).offset(offset)
        result = await self.db.execute(query)
        transactions = result.scalars().all()
        
        return transactions, total