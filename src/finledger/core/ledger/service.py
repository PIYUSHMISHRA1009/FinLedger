"""
FinLedger Ledger Service - Double-Entry Accounting Engine

Core implementation of the immutable double-entry ledger.
"""

from contextlib import asynccontextmanager
from dataclasses import dataclass
from decimal import Decimal
from typing import List, Optional, Dict, Any
from uuid import UUID, uuid4
from datetime import datetime, timezone

from sqlalchemy import select, func, update, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from finledger.db.models import (
    LedgerAccount,
    LedgerTransaction,
    LedgerEntry,
    AccountBalance,
    Transaction,
    Wallet,
    LedgerTxnStatus,
    LedgerEntryType,
    AccountType,
    AccountNormality,
)
from finledger.core.ledger.exceptions import (
    LedgerValidationError,
    AccountNotFoundError,
    InsufficientBalanceError,
    OptimisticLockError,
    LedgerImbalanceError,
)


@dataclass
class LedgerEntrySpec:
    """Specification for a single ledger entry."""
    account_code: str
    entry_type: LedgerEntryType
    amount: Decimal
    description: Optional[str] = None
    wallet_id: Optional[UUID] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class BalanceResult:
    """Result of a balance query."""
    posted: Decimal
    pending: Decimal
    available: Decimal
    currency: str
    as_of: datetime


class LedgerService:
    """
    Core double-entry ledger engine.
    
    Handles creation of balanced transactions, balance computation,
    and materialized view updates.
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_account_by_code(self, code: str) -> LedgerAccount:
        """Get ledger account by code."""
        result = await self.db.execute(
            select(LedgerAccount).where(
                LedgerAccount.code == code,
                LedgerAccount.is_active == True,
            )
        )
        account = result.scalar_one_or_none()
        if not account:
            raise AccountNotFoundError(f"Account not found: {code}")
        return account
    
    async def get_account(self, account_id: UUID) -> LedgerAccount:
        """Get ledger account by ID."""
        result = await self.db.execute(
            select(LedgerAccount).where(
                LedgerAccount.id == account_id,
                LedgerAccount.is_active == True,
            )
        )
        account = result.scalar_one_or_none()
        if not account:
            raise AccountNotFoundError(f"Account not found: {account_id}")
        return account
    
    def _validate_balanced(self, entries: List[LedgerEntrySpec]) -> None:
        """Validate that debits equal credits."""
        if len(entries) < 2:
            raise LedgerValidationError("Transaction must have at least 2 entries")
        
        debits = sum(e.amount for e in entries if e.entry_type == LedgerEntryType.DEBIT)
        credits = sum(e.amount for e in entries if e.entry_type == LedgerEntryType.CREDIT)
        
        if debits != credits:
            raise LedgerImbalanceError(
                f"Transaction not balanced: debits={debits}, credits={credits}"
            )
    
    async def _resolve_accounts(self, entries: List[LedgerEntrySpec]) -> Dict[str, LedgerAccount]:
        """Resolve account codes to LedgerAccount objects."""
        accounts = {}
        for entry in entries:
            if entry.account_code not in accounts:
                account = await self.get_account_by_code(entry.account_code)
                accounts[entry.account_code] = account
        return accounts
    
    def _calculate_balance_deltas(
        self,
        account: LedgerAccount,
        entry_type: LedgerEntryType,
        amount: Decimal,
    ) -> tuple[Decimal, Decimal, Decimal]:
        """
        Calculate balance deltas based on account normality and entry type.
        
        Returns:
            Tuple of (posted_delta, pending_delta, available_delta)
        """
        # For DEBIT-normal accounts (ASSET, EXPENSE):
        #   DEBIT increases balance, CREDIT decreases
        # For CREDIT-normal accounts (LIABILITY, EQUITY, REVENUE):
        #   CREDIT increases balance, DEBIT decreases
        
        is_debit_normal = account.normality == AccountNormality.DEBIT
        is_debit_entry = entry_type == LedgerEntryType.DEBIT
        
        # Determine if this entry increases or decreases the account
        increases = (is_debit_normal and is_debit_entry) or (not is_debit_normal and not is_debit_entry)
        
        sign = Decimal("1") if increases else Decimal("-1")
        posted_delta = sign * amount
        pending_delta = sign * amount
        
        # Available balance: conservative - only count posted inflows, not pending inflows
        if is_debit_entry:
            # DEBIT entry: increases asset/expense or decreases liability/equity
            # For available: only count if posted (conservative)
            available_delta = posted_delta
        else:
            # CREDIT entry: decreases asset/expense or increases liability/equity
            # For available: always count (conservative - pending outflows reduce available)
            available_delta = pending_delta
        
        return posted_delta, pending_delta, available_delta
    
    @asynccontextmanager
    async def transaction(self):
        """Context manager for database transaction with retry on optimistic lock."""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with self.db.begin():
                    yield
                return
            except Exception as e:
                if "OptimisticLockError" in str(type(e)) or "could not serialize" in str(e).lower():
                    if attempt < max_retries - 1:
                        await self.db.rollback()
                        import asyncio
                        await asyncio.sleep(0.01 * (attempt + 1))
                        continue
                raise
    
    async def create_transaction(
        self,
        reference: str,
        description: str,
        entries: List[LedgerEntrySpec],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> LedgerTransaction:
        """
        Create a balanced ledger transaction with entries.
        
        Args:
            reference: Human-readable reference (e.g., "TXN-20240115-001")
            description: Transaction description
            entries: List of entry specifications
            metadata: Additional context
            
        Returns:
            Created LedgerTransaction with entries
            
        Raises:
            LedgerValidationError: If validation fails
            LedgerImbalanceError: If debits != credits
            AccountNotFoundError: If account not found
        """
        # Validate
        self._validate_balanced(entries)
        accounts = await self._resolve_accounts(entries)
        
        # Create transaction header
        txn = LedgerTransaction(
            reference=reference,
            description=description,
            status=LedgerTxnStatus.POSTED,
            posted_at=datetime.now(timezone.utc),
            metadata=metadata or {},
        )
        self.db.add(txn)
        await self.db.flush()  # Get txn.id
        
        # Create entries with sequence
        for i, entry_spec in enumerate(entries):
            account = accounts[entry_spec.account_code]
            
            entry = LedgerEntry(
                ledger_transaction_id=txn.id,
                ledger_account_id=account.id,
                wallet_id=entry_spec.wallet_id,
                entry_type=entry_spec.entry_type,
                amount=entry_spec.amount,
                description=entry_spec.description or description,
                sequence=i,
                metadata=entry_spec.metadata or {},
            )
            self.db.add(entry)
        
        # Update materialized balances
        await self._update_balances(txn.id, entries, accounts)
        
        await self.db.commit()
        await self.db.refresh(txn)
        
        return txn
    
    async def _update_balances(
        self,
        txn_id: UUID,
        entries: List[LedgerEntrySpec],
        accounts: Dict[str, LedgerAccount],
    ) -> None:
        """Update materialized account_balances table."""
        for entry_spec in entries:
            account = accounts[entry_spec.account_code]
            wallet_id = entry_spec.wallet_id
            amount = entry_spec.amount
            entry_type = entry_spec.entry_type
            
            posted_delta, pending_delta, available_delta = self._calculate_balance_deltas(
                account, entry_type, amount
            )
            
            # Upsert balance with optimistic locking
            stmt = pg_insert(AccountBalance).values(
                ledger_account_id=account.id,
                wallet_id=wallet_id,
                posted_balance=posted_delta,
                pending_balance=pending_delta,
                available_balance=available_delta,
                version=1,
                last_transaction_id=txn_id,
                updated_at=datetime.now(timezone.utc),
            ).on_conflict_do_update(
                index_elements=["ledger_account_id", "wallet_id"],
                set_={
                    "posted_balance": AccountBalance.posted_balance + posted_delta,
                    "pending_balance": AccountBalance.pending_balance + pending_delta,
                    "available_balance": AccountBalance.available_balance + available_delta,
                    "version": AccountBalance.version + 1,
                    "last_transaction_id": txn_id,
                    "updated_at": datetime.now(timezone.utc),
                },
            )
            await self.db.execute(stmt)
    
    async def get_balance(
        self,
        account_code: str,
        wallet_id: Optional[UUID] = None,
        as_of: Optional[datetime] = None,
    ) -> BalanceResult:
        """
        Get balance for an account (optionally filtered by wallet).
        
        Args:
            account_code: Account code (e.g., "1010")
            wallet_id: Optional wallet filter
            as_of: Point-in-time query (uses materialized view if None)
            
        Returns:
            BalanceResult with posted, pending, available balances
        """
        account = await self.get_account_by_code(account_code)
        
        # Get currency from account or wallet
        currency = account.currency
        if not currency and wallet_id:
            wallet = await self.db.get(Wallet, wallet_id)
            currency = wallet.currency if wallet else "USD"
        
        # If as_of is specified, compute from ledger entries
        if as_of:
            return await self._compute_balance_at_time(account.id, wallet_id, as_of, currency)
        
        # Otherwise use materialized view
        result = await self.db.execute(
            select(AccountBalance).where(
                AccountBalance.ledger_account_id == account.id,
                AccountBalance.wallet_id == wallet_id,
            )
        )
        balance = result.scalar_one_or_none()
        
        if balance:
            return BalanceResult(
                posted=balance.posted_balance,
                pending=balance.pending_balance,
                available=balance.available_balance,
                currency=currency or "USD",
                as_of=balance.updated_at,
            )
        
        return BalanceResult(
            posted=Decimal("0"),
            pending=Decimal("0"),
            available=Decimal("0"),
            currency=currency or "USD",
            as_of=datetime.now(timezone.utc),
        )
    
    async def _compute_balance_at_time(
        self,
        account_id: UUID,
        wallet_id: Optional[UUID],
        as_of: datetime,
        currency: str,
    ) -> BalanceResult:
        """Compute balance from ledger entries at a point in time."""
        # Posted: only POSTED transactions
        posted_query = select(
            func.coalesce(func.sum(
                func.case(
                    (LedgerEntry.entry_type == LedgerEntryType.DEBIT, LedgerEntry.amount),
                    else_=-LedgerEntry.amount,
                )
            ), Decimal("0"))
        ).select_from(
            LedgerEntry.__table__.join(LedgerTransaction)
        ).where(
            LedgerEntry.ledger_account_id == account_id,
            LedgerTransaction.status == LedgerTxnStatus.POSTED,
            LedgerTransaction.posted_at <= as_of,
        )
        
        if wallet_id:
            posted_query = posted_query.where(LedgerEntry.wallet_id == wallet_id)
        
        # Pending: all transactions (POSTED + DRAFT)
        pending_query = select(
            func.coalesce(func.sum(
                func.case(
                    (LedgerEntry.entry_type == LedgerEntryType.DEBIT, LedgerEntry.amount),
                    else_=-LedgerEntry.amount,
                )
            ), Decimal("0"))
        ).select_from(
            LedgerEntry.__table__.join(LedgerTransaction)
        ).where(
            LedgerEntry.ledger_account_id == account_id,
            LedgerTransaction.created_at <= as_of,
        )
        
        if wallet_id:
            pending_query = pending_query.where(LedgerEntry.wallet_id == wallet_id)
        
        # Available: Posted inflows - (Posted + Pending) outflows
        available_query = select(
            func.coalesce(func.sum(
                func.case(
                    (and_(
                        LedgerEntry.entry_type == LedgerEntryType.DEBIT,
                        LedgerTransaction.status == LedgerTxnStatus.POSTED,
                    ), LedgerEntry.amount),
                    (and_(
                        LedgerEntry.entry_type == LedgerEntryType.CREDIT,
                        LedgerTransaction.status == LedgerTxnStatus.POSTED,
                    ), -LedgerEntry.amount),
                    (and_(
                        LedgerEntry.entry_type == LedgerEntryType.CREDIT,
                        LedgerTransaction.status != LedgerTxnStatus.POSTED,
                    ), -LedgerEntry.amount),
                    else_=Decimal("0"),
                )
            ), Decimal("0"))
        ).select_from(
            LedgerEntry.__table__.join(LedgerTransaction)
        ).where(
            LedgerEntry.ledger_account_id == account_id,
            LedgerTransaction.created_at <= as_of,
        )
        
        if wallet_id:
            available_query = available_query.where(LedgerEntry.wallet_id == wallet_id)
        
        posted = await self.db.scalar(posted_query) or Decimal("0")
        pending = await self.db.scalar(pending_query) or Decimal("0")
        available = await self.db.scalar(available_query) or Decimal("0")
        
        return BalanceResult(
            posted=posted,
            pending=pending,
            available=available,
            currency=currency,
            as_of=as_of,
        )
    
    async def get_wallet_balances(self, wallet_id: UUID) -> Dict[str, BalanceResult]:
        """Get all three balance types for a wallet."""
        # Get all account balances for this wallet
        result = await self.db.execute(
            select(AccountBalance, LedgerAccount)
            .join(LedgerAccount)
            .where(AccountBalance.wallet_id == wallet_id)
        )
        
        balances = {}
        for bal, account in result:
            if account.account_type == AccountType.ASSET:
                # For assets, positive balance means we hold funds
                pass
            elif account.account_type == AccountType.LIABILITY:
                # For liabilities, negative balance means customer funds
                pass
            
            balances[account.code] = BalanceResult(
                posted=bal.posted_balance,
                pending=bal.pending_balance,
                available=bal.available_balance,
                currency=account.currency or "USD",
                as_of=bal.updated_at,
            )
        
        return balances
    
    async def get_trial_balance(self, as_of: Optional[datetime] = None) -> Dict[str, Any]:
        """Generate trial balance: all accounts with net balances."""
        if as_of:
            # Compute from ledger entries
            result = await self.db.execute(
                select(
                    LedgerAccount.code,
                    LedgerAccount.name,
                    LedgerAccount.account_type,
                    LedgerAccount.normality,
                    func.coalesce(func.sum(
                        func.case(
                            (LedgerEntry.entry_type == LedgerEntryType.DEBIT, LedgerEntry.amount),
                            else_=-LedgerEntry.amount,
                        )
                    ), Decimal("0")).label("net_balance"),
                )
                .select_from(
                    LedgerAccount.__table__.outerjoin(
                        LedgerEntry,
                        and_(
                            LedgerEntry.ledger_account_id == LedgerAccount.id,
                            LedgerEntry.ledger_transaction_id == LedgerTransaction.id,
                        )
                    ).outerjoin(LedgerTransaction)
                )
                .where(
                    LedgerAccount.is_active == True,
                    LedgerTransaction.posted_at <= as_of,
                    LedgerTransaction.status == LedgerTxnStatus.POSTED,
                )
                .group_by(
                    LedgerAccount.id, LedgerAccount.code, LedgerAccount.name,
                    LedgerAccount.account_type, LedgerAccount.normality
                )
                .order_by(LedgerAccount.code)
            )
        else:
            # Use materialized balances
            result = await self.db.execute(
                select(
                    LedgerAccount.code,
                    LedgerAccount.name,
                    LedgerAccount.account_type,
                    LedgerAccount.normality,
                    func.coalesce(func.sum(AccountBalance.posted_balance), Decimal("0")).label("net_balance"),
                )
                .join(AccountBalance, AccountBalance.ledger_account_id == LedgerAccount.id, isouter=True)
                .where(LedgerAccount.is_active == True)
                .group_by(
                    LedgerAccount.id, LedgerAccount.code, LedgerAccount.name,
                    LedgerAccount.account_type, LedgerAccount.normality
                )
                .order_by(LedgerAccount.code)
            )
        
        accounts = []
        total_debits = Decimal("0")
        total_credits = Decimal("0")
        
        for row in result:
            net = row.net_balance
            if row.normality == AccountNormality.DEBIT:
                if net >= 0:
                    total_debits += net
                else:
                    total_credits += abs(net)
            else:
                if net >= 0:
                    total_credits += net
                else:
                    total_debits += abs(net)
            
            accounts.append({
                "code": row.code,
                "name": row.name,
                "account_type": row.account_type.value,
                "normality": row.normality.value,
                "net_balance": str(net),
            })
        
        return {
            "accounts": accounts,
            "total_debits": str(total_debits),
            "total_credits": str(total_credits),
            "balanced": total_debits == total_credits,
            "as_of": as_of.isoformat() if as_of else datetime.now(timezone.utc).isoformat(),
        }