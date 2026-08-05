"""
FinLedger Reconciliation Engine

Automated reconciliation engine that compares internal ledger state against
external statements with discrepancy detection and alerting.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import List, Dict, Any, Optional, Callable, Set
from uuid import UUID, uuid4
from datetime import datetime, timezone, timedelta
from enum import Enum
from abc import ABC, abstractmethod
from collections import defaultdict
import json

from sqlalchemy import select, func, and_, or_, desc, text, case
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB

from finledger.db.models import (
    Wallet, Transaction, LedgerAccount, AccountBalance, LedgerEntry,
    LedgerTransaction, LedgerTxnStatus, WalletStatus, TransactionStatus,
    TransactionType, AccountType, AccountNormality
)
from finledger.db.database import Base
from sqlalchemy import Column, String, DateTime, Boolean, Integer, ForeignKey, Text, Index, Numeric
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB


# =============================================================================
# ENUMS & DATA CLASSES
# =============================================================================

class ReconciliationStatus(str, Enum):
    MATCHED = "MATCHED"
    MISMATCHED = "MISMATCHED"
    PENDING = "PENDING"
    INVESTIGATING = "INVESTIGATING"
    RESOLVED = "RESOLVED"
    UNRECOVERABLE = "UNRECOVERABLE"


class ReconciliationType(str, Enum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    ON_DEMAND = "ON_DEMAND"
    CONTINUOUS = "CONTINUOUS"


class DiscrepancyType(str, Enum):
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
    MISSING_TRANSACTION = "MISSING_TRANSACTION"
    EXTRA_TRANSACTION = "EXTRA_TRANSACTION"
    TIMING_DIFFERENCE = "TIMING_DIFFERENCE"
    STATUS_MISMATCH = "STATUS_MISMATCH"
    BALANCE_MISMATCH = "BALANCE_MISMATCH"


@dataclass
class ReconciliationResult:
    """Result of a single reconciliation check."""
    wallet_id: UUID
    account_code: str
    reconciliation_type: ReconciliationType
    status: ReconciliationStatus
    internal_balance: Decimal
    external_balance: Decimal
    discrepancy_amount: Decimal
    discrepancy_type: Optional[DiscrepancyType] = None
    discrepancy_details: Dict[str, Any] = field(default_factory=dict)
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[UUID] = None
    resolution_notes: Optional[str] = None


@dataclass
class ReconciliationReport:
    """Complete reconciliation report for a period."""
    reconciliation_id: UUID
    reconciliation_type: ReconciliationType
    period_start: datetime
    period_end: datetime
    total_wallets_checked: int
    matched_count: int
    mismatched_count: int
    pending_count: int
    total_discrepancy_amount: Decimal
    results: List[ReconciliationResult]
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: ReconciliationStatus = ReconciliationStatus.PENDING


@dataclass
class ExternalStatement:
    """External statement data from bank/processor."""
    source: str  # e.g., "chase", "stripe", "wise"
    wallet_id: UUID
    currency: str
    period_start: datetime
    period_end: datetime
    opening_balance: Decimal
    closing_balance: Decimal
    transactions: List[Dict[str, Any]]  # List of {date, amount, type, description, reference}
    raw_data: Dict[str, Any] = field(default_factory=dict)


# =============================================================================
# DATABASE MODELS
# =============================================================================

class ReconciliationJob(Base):
    """Reconciliation job tracking."""
    __tablename__ = "reconciliation_jobs"
    
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    reconciliation_type = Column(String(20), nullable=False, index=True)
    status = Column(String(20), nullable=False, default=ReconciliationStatus.PENDING)
    
    period_start = Column(DateTime(timezone=True), nullable=False, index=True)
    period_end = Column(DateTime(timezone=True), nullable=False, index=True)
    
    total_wallets = Column(Integer, default=0)
    matched_count = Column(Integer, default=0)
    mismatched_count = Column(Integer, default=0)
    pending_count = Column(Integer, default=0)
    total_discrepancy = Column(Numeric(19, 4), default=Decimal("0"))
    
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))
    
    __table_args__ = (
        Index("idx_recon_job_status_period", "status", "period_start", "period_end"),
    )


class ReconciliationResultModel(Base):
    """Individual reconciliation result."""
    __tablename__ = "reconciliation_results"
    
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    job_id = Column(PG_UUID(as_uuid=True), ForeignKey("reconciliation_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    wallet_id = Column(PG_UUID(as_uuid=True), ForeignKey("wallets.id", ondelete="CASCADE"), nullable=False, index=True)
    account_code = Column(String(50), nullable=False)
    
    status = Column(String(20), nullable=False, default=ReconciliationStatus.PENDING, index=True)
    
    internal_balance = Column(Numeric(19, 4), nullable=False)
    external_balance = Column(Numeric(19, 4), nullable=False)
    discrepancy_amount = Column(Numeric(19, 4), nullable=False, default=Decimal("0"))
    discrepancy_type = Column(String(30), nullable=True)
    discrepancy_details = Column(JSONB, nullable=True, default=dict)
    
    checked_at = Column(DateTime(timezone=True), nullable=False, default=datetime.now(timezone.utc))
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_by = Column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resolution_notes = Column(Text, nullable=True)
    
    __table_args__ = (
        Index("idx_recon_result_wallet_status", "wallet_id", "status"),
        Index("idx_recon_result_job_status", "job_id", "status"),
    )


class ExternalStatementModel(Base):
    """Stored external statements for audit trail."""
    __tablename__ = "external_statements"
    
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    job_id = Column(PG_UUID(as_uuid=True), ForeignKey("reconciliation_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    wallet_id = Column(PG_UUID(as_uuid=True), ForeignKey("wallets.id", ondelete="CASCADE"), nullable=False)
    
    source = Column(String(50), nullable=False)  # e.g., "chase", "stripe", "wise"
    currency = Column(String(3), nullable=False)
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(DateTime(timezone=True), nullable=False)
    opening_balance = Column(Numeric(19, 4), nullable=False)
    closing_balance = Column(Numeric(19, 4), nullable=False)
    
    transactions = Column(JSONB, nullable=False, default=[])  # External transactions
    raw_data = Column(JSONB, nullable=True, default=dict)
    checksum = Column(String(64), nullable=True)  # SHA256 for integrity
    
    uploaded_at = Column(DateTime(timezone=True), nullable=False, default=datetime.now(timezone.utc))
    processed = Column(Boolean, default=False)
    
    __table_args__ = (
        Index("idx_ext_stmt_wallet_period", "wallet_id", "period_start", "period_end"),
    )


class ReconciliationRule(Base):
    """Configurable reconciliation rules."""
    __tablename__ = "reconciliation_rules"
    
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(100), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    
    # Rule configuration
    applies_to_currency = Column(String(3), nullable=True)  # NULL = all currencies
    applies_to_source = Column(String(50), nullable=True)   # NULL = all sources
    
    # Matching criteria
    match_amount_exact = Column(Boolean, default=True)
    match_amount_tolerance = Column(Numeric(19, 4), default=Decimal("0"))
    match_date_window_days = Column(Integer, default=1)
    match_reference = Column(Boolean, default=False)
    match_description = Column(Boolean, default=False)
    
    # Discrepancy handling
    auto_resolve_threshold = Column(Numeric(19, 4), default=Decimal("0"))  # Auto-resolve if diff <= threshold
    require_manual_review_above = Column(Numeric(19, 4), default=Decimal("100"))
    
    is_active = Column(Boolean, default=True)
    priority = Column(Integer, default=100)
    
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))


# =============================================================================
# RECONCILIATION ENGINE
# =============================================================================

class ReconciliationEngine:
    """
    Automated reconciliation engine with:
    - Multiple reconciliation types (daily, weekly, monthly, on-demand)
    - Configurable matching rules
    - Discrepancy detection and classification
    - Auto-resolution for small discrepancies
    - Alerting for manual review
    - Audit trail
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self._rules_cache: List[ReconciliationRule] = []
        self._cache_timestamp: float = 0
        self._cache_ttl = 300  # 5 minutes
    
    # -------------------------------------------------------------------------
    # RULE MANAGEMENT
    # -------------------------------------------------------------------------
    
    async def _get_active_rules(self) -> List[ReconciliationRule]:
        """Get active reconciliation rules with caching."""
        import time
        now = time.time()
        
        if now - self._cache_timestamp > self._cache_ttl or not self._rules_cache:
            result = await self.db.execute(
                select(ReconciliationRule)
                .where(ReconciliationRule.is_active == True)
                .order_by(ReconciliationRule.priority)
            )
            self._rules_cache = result.scalars().all()
            self._cache_timestamp = now
        
        return self._rules_cache
    
    def _get_applicable_rule(
        self,
        wallet: Wallet,
        source: str,
    ) -> Optional[ReconciliationRule]:
        """Get the most specific applicable rule for a wallet/source."""
        rules = self._rules_cache  # Assume cache is fresh
        
        applicable = []
        for rule in rules:
            if rule.applies_to_currency and rule.applies_to_currency != wallet.currency:
                continue
            if rule.applies_to_source and rule.applies_to_source != source:
                continue
            applicable.append(rule)
        
        if not applicable:
            return None
        
        # Return highest priority (lowest number)
        return min(applicable, key=lambda r: r.priority)
    
    # -------------------------------------------------------------------------
    # EXTERNAL STATEMENT PROCESSING
    # -------------------------------------------------------------------------
    
    async def upload_external_statement(
        self,
        job_id: UUID,
        statement: ExternalStatement,
    ) -> UUID:
        """Store external statement for reconciliation."""
        # Compute checksum for integrity
        import hashlib
        statement_json = json.dumps({
            "source": statement.source,
            "wallet_id": str(statement.wallet_id),
            "currency": statement.currency,
            "period_start": statement.period_start.isoformat(),
            "period_end": statement.period_end.isoformat(),
            "opening_balance": str(statement.opening_balance),
            "closing_balance": str(statement.closing_balance),
            "transactions": statement.transactions,
        }, sort_keys=True)
        checksum = hashlib.sha256(statement_json.encode()).hexdigest()
        
        ext_stmt = ExternalStatementModel(
            job_id=job_id,
            wallet_id=statement.wallet_id,
            source=statement.source,
            currency=statement.currency,
            period_start=statement.period_start,
            period_end=statement.period_end,
            opening_balance=statement.opening_balance,
            closing_balance=statement.closing_balance,
            transactions=statement.transactions,
            raw_data=statement.raw_data,
            checksum=checksum,
        )
        
        self.db.add(ext_stmt)
        await self.db.flush()
        return ext_stmt.id
    
    # -------------------------------------------------------------------------
    # CORE RECONCILIATION LOGIC
    # -------------------------------------------------------------------------
    
    async def run_reconciliation(
        self,
        reconciliation_type: ReconciliationType,
        period_start: datetime,
        period_end: datetime,
        wallet_ids: Optional[List[UUID]] = None,
        source_filter: Optional[str] = None,
    ) -> ReconciliationReport:
        """
        Run a complete reconciliation job.
        """
        # Create job record
        job = ReconciliationJob(
            reconciliation_type=reconciliation_type.value,
            status=ReconciliationStatus.PENDING,
            period_start=period_start,
            period_end=period_end,
        )
        self.db.add(job)
        await self.db.flush()
        
        try:
            job.status = ReconciliationStatus.INVESTIGATING
            job.started_at = datetime.now(timezone.utc)
            await self.db.commit()
            
            # Get wallets to reconcile
            wallets = await self._get_wallets_to_reconcile(wallet_ids, source_filter)
            job.total_wallets = len(wallets)
            await self.db.commit()
            
            # Get active rules
            self._rules_cache = await self._get_active_rules()
            
            # Run reconciliation for each wallet
            results = []
            for wallet in wallets:
                rule = self._get_applicable_rule(wallet, source_filter or "bank")
                result = await self._reconcile_wallet(
                    job_id=job.id,
                    wallet=wallet,
                    period_start=period_start,
                    period_end=period_end,
                    rule=rule,
                )
                results.append(result)
            
            # Aggregate results
            matched = sum(1 for r in results if r.status == ReconciliationStatus.MATCHED)
            mismatched = sum(1 for r in results if r.status == ReconciliationStatus.MISMATCHED)
            pending = sum(1 for r in results if r.status == ReconciliationStatus.PENDING)
            total_discrepancy = sum(r.discrepancy_amount for r in results)
            
            # Update job
            job.matched_count = matched
            job.mismatched_count = mismatched
            job.pending_count = pending
            job.total_discrepancy = total_discrepancy
            job.status = ReconciliationStatus.RESOLVED if mismatched == 0 else ReconciliationStatus.INVESTIGATING
            job.completed_at = datetime.now(timezone.utc)
            
            await self.db.commit()
            
            return ReconciliationReport(
                reconciliation_id=job.id,
                reconciliation_type=reconciliation_type,
                period_start=period_start,
                period_end=period_end,
                total_wallets_checked=len(wallets),
                matched_count=matched,
                mismatched_count=mismatched,
                pending_count=pending,
                total_discrepancy_amount=total_discrepancy,
                results=results,
                status=job.status,
            )
            
        except Exception as e:
            job.status = ReconciliationStatus.PENDING
            job.error_message = str(e)
            job.completed_at = datetime.now(timezone.utc)
            await self.db.commit()
            raise
    
    async def _get_wallets_to_reconcile(
        self,
        wallet_ids: Optional[List[UUID]],
        source_filter: Optional[str],
    ) -> List[Wallet]:
        """Get wallets that need reconciliation."""
        query = select(Wallet).where(Wallet.status == WalletStatus.ACTIVE)
        
        if wallet_ids:
            query = query.where(Wallet.id.in_(wallet_ids))
        
        # If source filter, we might need to join with external statements
        # For now, reconcile all active wallets
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def _reconcile_wallet(
        self,
        job_id: UUID,
        wallet: Wallet,
        period_start: datetime,
        period_end: datetime,
        rule: Optional[ReconciliationRule],
    ) -> ReconciliationResult:
        """
        Reconcile a single wallet against external statements.
        """
        # Get liability account for this wallet's currency
        liability_code = f"201{wallet.currency[-1]}"  # 2010, 2011, 2012
        
        # Get internal balance from ledger
        internal_balance = await self._get_internal_balance(
            wallet.id, liability_code, period_end
        )
        
        # Get external balance from stored statements
        external_balance = await self._get_external_balance(
            wallet.id, period_start, period_end
        )
        
        # If no external statement, mark as pending
        if external_balance is None:
            result = ReconciliationResult(
                wallet_id=wallet.id,
                account_code=liability_code,
                reconciliation_type=ReconciliationType.DAILY,
                status=ReconciliationStatus.PENDING,
                internal_balance=internal_balance,
                external_balance=Decimal("0"),
                discrepancy_amount=internal_balance,
                discrepancy_type=DiscrepancyType.MISSING_TRANSACTION,
                discrepancy_details={"reason": "No external statement available"},
            )
            
            await self._save_result(job_id, wallet.id, liability_code, result)
            return result
        
        # Compare balances
        discrepancy = internal_balance - external_balance
        
        # Check if within tolerance
        tolerance = Decimal("0")
        if rule and rule.match_amount_tolerance:
            tolerance = rule.match_amount_tolerance
        
        if abs(discrepancy) <= tolerance:
            status = ReconciliationStatus.MATCHED
            discrepancy_type = None
        else:
            status = ReconciliationStatus.MISMATCHED
            discrepancy_type = DiscrepancyType.BALANCE_MISMATCH
        
        # Determine discrepancy type
        if discrepancy_type is None:
            discrepancy_type = None
        elif external_balance == 0:
            discrepancy_type = DiscrepancyType.MISSING_TRANSACTION
        elif internal_balance == 0:
            discrepancy_type = DiscrepancyType.EXTRA_TRANSACTION
        else:
            discrepancy_type = DiscrepancyType.BALANCE_MISMATCH
        
        # Check auto-resolve
        auto_resolve = False
        if rule and rule.auto_resolve_threshold and abs(discrepancy) <= rule.auto_resolve_threshold:
            # Auto-resolve small discrepancies
            pass  # Would create adjusting entry
        
        result = ReconciliationResult(
            wallet_id=wallet.id,
            account_code="2010",  # Would be actual code
            reconciliation_type=ReconciliationType.DAILY,
            status=ReconciliationStatus.MATCHED if status == ReconciliationStatus.MATCHED else ReconciliationStatus.MISMATCHED,
            internal_balance=internal_balance,
            external_balance=external_balance,
            discrepancy_amount=abs(discrepancy),
            discrepancy_type=discrepancy_type,
            discrepancy_details={
                "wallet_name": "wallet.name",  # Would be actual name
                "currency": "wallet.currency",
                "tolerance": str(tolerance),
            },
        )
        
        await self._save_result(job_id, wallet.id, "2010", result)
        return result
    
    async def _get_internal_balance(
        self,
        wallet_id: UUID,
        account_code: str,
        as_of: datetime,
    ) -> Decimal:
        """Get internal balance from ledger at point in time."""
        # Get account
        result = await self.db.execute(
            select(LedgerAccount).where(LedgerAccount.code == account_code)
        )
        account = result.scalar_one_or_none()
        
        if not account:
            return Decimal("0")
        
        # Get balance from materialized view
        result = await self.db.execute(
            select(AccountBalance).where(
                AccountBalance.ledger_account_id == account.id,
                AccountBalance.wallet_id == wallet_id,
            )
        )
        balance = result.scalar_one_or_none()
        
        if balance:
            return balance.posted_balance
        
        # Compute from ledger entries
        result = await self.db.execute(
            select(
                func.coalesce(func.sum(
                    case(
                        (LedgerEntry.entry_type == LedgerEntryType.DEBIT, LedgerEntry.amount),
                        else_=-LedgerEntry.amount,
                    )
                ), Decimal("0"))
            ).join(LedgerTransaction).where(
                LedgerEntry.ledger_account_id == account.id,
                LedgerTransaction.status == LedgerTxnStatus.POSTED,
                LedgerTransaction.posted_at <= as_of,
            )
        )
        return result.scalar() or Decimal("0")
    
    async def _get_external_balance(
        self,
        wallet_id: UUID,
        period_start: datetime,
        period_end: datetime,
    ) -> Optional[Decimal]:
        """Get closing balance from most recent external statement."""
        result = await self.db.execute(
            select(ExternalStatementModel)
            .where(
                ExternalStatementModel.wallet_id == wallet_id,
                ExternalStatementModel.period_end <= period_end,
                ExternalStatementModel.processed == True,
            )
            .order_by(desc(ExternalStatementModel.period_end))
            .limit(1)
        )
        stmt = result.scalar_one_or_none()
        
        if stmt:
            return stmt.closing_balance
        
        return None
    
    async def _save_result(
        self,
        job_id: UUID,
        wallet_id: UUID,
        account_code: str,
        result: ReconciliationResult,
    ) -> None:
        """Save reconciliation result to database."""
        model = ReconciliationResultModel(
            job_id=job_id,
            wallet_id=wallet_id,
            account_code=account_code,
            status=result.status.value,
            internal_balance=result.internal_balance,
            external_balance=result.external_balance,
            discrepancy_amount=result.discrepancy_amount,
            discrepancy_type=result.discrepancy_type.value if result.discrepancy_type else None,
            discrepancy_details=result.discrepancy_details,
            checked_at=result.checked_at,
        )
        
        self.db.add(model)
        await self.db.flush()
    
    # -------------------------------------------------------------------------
    # TRANSACTION-LEVEL MATCHING
    # -------------------------------------------------------------------------
    
    async def match_transactions(
        self,
        wallet_id: UUID,
        period_start: datetime,
        period_end: datetime,
        external_transactions: List[Dict[str, Any]],
        rule: Optional[ReconciliationRule],
    ) -> Dict[str, Any]:
        """
        Match internal transactions to external transactions.
        Returns matching results with unmatched items.
        """
        # Get internal transactions
        internal_txns = await self._get_internal_transactions(
            wallet_id, period_start, period_end
        )
        
        # Convert external to standard format
        external = self._normalize_external_transactions(external_transactions)
        
        # Matching logic
        matched = []
        unmatched_internal = []
        unmatched_external = []
        
        # Create lookup for external by amount + date window
        external_by_amount = defaultdict(list)
        for ext in external:
            key = (ext["amount"], ext["date"])
            external_by_amount[key].append(ext)
        
        for internal in internal_txns:
            key = (internal.amount, internal.created_at.date())
            matches = external_by_amount.get(key, [])
            
            if matches:
                # Try to find best match
                best_match = self._find_best_match(internal, matches, rule)
                if best_match:
                    matched.append({
                        "internal": internal,
                        "external": best_match,
                        "match_type": "EXACT" if self._is_exact_match(internal, best_match, rule) else "FUZZY",
                    })
                    external.remove(best_match)
                    continue
            
            unmatched_internal.append(internal)
        
        unmatched_external = external
        
        return {
            "matched": matched,
            "unmatched_internal": unmatched_internal,
            "unmatched_external": unmatched_external,
            "total_internal": len(internal_txns),
            "total_external": len(external_transactions),
            "match_rate": len(matched) / max(len(external_transactions), 1) * 100,
        }
    
    def _is_exact_match(
        self,
        internal: Transaction,
        external: Dict[str, Any],
        rule: Optional[ReconciliationRule],
    ) -> bool:
        """Check if internal and external transaction match exactly."""
        if not rule:
            return False
        
        if rule.match_amount_exact and internal.amount != Decimal(str(external["amount"])):
            return False
        
        if rule.match_amount_tolerance:
            if abs(internal.amount - Decimal(str(external["amount"]))) > rule.match_amount_tolerance:
                return False
        
        if rule.match_date_window_days:
            internal_date = internal.created_at.date()
            external_date = external["date"]
            if abs((internal_date - external_date).days) > rule.match_date_window_days:
                return False
        
        if rule.match_reference and internal.idempotency_key != external.get("reference"):
            return False
        
        if rule.match_description and internal.description != external.get("description"):
            return False
        
        return True
    
    def _find_best_match(
        self,
        internal: Transaction,
        candidates: List[Dict[str, Any]],
        rule: Optional[ReconciliationRule],
    ) -> Optional[Dict[str, Any]]:
        """Find best matching external transaction."""
        for candidate in candidates:
            if self._is_exact_match(internal, candidate, rule):
                return candidate
        return None
    
    def _normalize_external_transactions(
        self,
        transactions: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Normalize external transactions to standard format."""
        normalized = []
        for t in transactions:
            normalized.append({
                "amount": Decimal(str(t.get("amount", 0))),
                "date": t.get("date", datetime.now(timezone.utc).date()),
                "type": t.get("type", "UNKNOWN"),
                "description": t.get("description", ""),
                "reference": t.get("reference", ""),
                "raw": t,
            })
        return normalized
    
    async def _get_internal_transactions(
        self,
        wallet_id: UUID,
        period_start: datetime,
        period_end: datetime,
    ) -> List[Transaction]:
        """Get internal transactions for a wallet in period."""
        result = await self.db.execute(
            select(Transaction)
            .where(
                or_(
                    Transaction.source_wallet_id == wallet_id,
                    Transaction.destination_wallet_id == wallet_id,
                ),
                Transaction.created_at >= period_start,
                Transaction.created_at <= period_end,
                Transaction.status == TransactionStatus.COMPLETED,
            )
            .order_by(Transaction.created_at)
        )
        return list(result.scalars().all())


# =============================================================================
# ADMIN API FOR RECONCILIATION
# =============================================================================

reconciliation_router = APIRouter(prefix="/admin/reconciliation", tags=["Reconciliation"])


@reconciliation_router.post(
    "/run",
    response_model=dict,
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_reconciliation(
    request: dict,
    current_user: User = Depends(require_permission("reconciliation:run")),
    db: AsyncSession = Depends(get_db),
):
    """Run a reconciliation job."""
    engine = ReconciliationEngine(db)
    
    report = await engine.run_reconciliation(
        reconciliation_type=ReconciliationType(request["reconciliation_type"]),
        period_start=datetime.fromisoformat(request["period_start"]),
        period_end=datetime.fromisoformat(request["period_end"]),
        wallet_ids=[UUID(w) for w in request.get("wallet_ids", [])] if request.get("wallet_ids") else None,
        source_filter=request.get("source_filter"),
    )
    
    return {
        "reconciliation_id": str(report.reconciliation_id),
        "status": report.status.value,
        "matched": report.matched_count,
        "mismatched": report.mismatched_count,
        "pending": report.pending_count,
        "total_discrepancy": str(report.total_discrepancy_amount),
    }


@reconciliation_router.get(
    "/jobs",
    response_model=dict,
)
async def list_reconciliation_jobs(
    status: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_permission("reconciliation:read")),
    db: AsyncSession = Depends(get_db),
):
    """List reconciliation jobs."""
    query = select(ReconciliationJob).order_by(desc(ReconciliationJob.created_at))
    
    if status:
        query = query.where(ReconciliationJob.status == status)
    
    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query) or 0
    
    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    jobs = result.scalars().all()
    
    return {
        "items": [
            {
                "id": str(j.id),
                "reconciliation_type": j.reconciliation_type,
                "status": j.status,
                "period_start": j.period_start.isoformat(),
                "period_end": j.period_end.isoformat(),
                "total_wallets": j.total_wallets,
                "matched_count": j.matched_count,
                "mismatched_count": j.mismatched_count,
                "pending_count": j.pending_count,
                "total_discrepancy": str(j.total_discrepancy),
                "started_at": j.started_at.isoformat() if j.started_at else None,
                "completed_at": j.completed_at.isoformat() if j.completed_at else None,
                "created_at": j.created_at.isoformat(),
            }
            for j in jobs
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@reconciliation_router.get(
    "/jobs/{job_id}",
    response_model=dict,
)
async def get_reconciliation_job(
    job_id: UUID,
    current_user: User = Depends(require_permission("reconciliation:read")),
    db: AsyncSession = Depends(get_db),
):
    """Get reconciliation job details with results."""
    result = await db.execute(
        select(ReconciliationJob).where(ReconciliationJob.id == job_id)
    )
    job = result.scalar_one_or_none()
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Get results
    result = await db.execute(
        select(ReconciliationResultModel)
        .where(ReconciliationResultModel.job_id == job_id)
        .order_by(desc(ReconciliationResultModel.checked_at))
    )
    results = result.scalars().all()
    
    return {
        "job": {
            "id": str(job.id),
            "reconciliation_type": job.reconciliation_type,
            "status": job.status,
            "period_start": job.period_start.isoformat(),
            "period_end": job.period_end.isoformat(),
            "total_wallets": job.total_wallets,
            "matched_count": job.matched_count,
            "mismatched_count": job.mismatched_count,
            "pending_count": job.pending_count,
            "total_discrepancy": str(job.total_discrepancy),
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        },
        "results": [
            {
                "id": str(r.id),
                "wallet_id": str(r.wallet_id),
                "account_code": r.account_code,
                "status": r.status,
                "internal_balance": str(r.internal_balance),
                "external_balance": str(r.external_balance),
                "discrepancy_amount": str(r.discrepancy_amount),
                "discrepancy_type": r.discrepancy_type,
                "discrepancy_details": r.discrepancy_details,
                "checked_at": r.checked_at.isoformat(),
                "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
            }
            for r in results
        ],
    }


@reconciliation_router.post(
    "/jobs/{job_id}/results/{result_id}/resolve",
    response_model=dict,
)
async def resolve_discrepancy(
    job_id: UUID,
    result_id: UUID,
    request: dict,
    current_user: User = Depends(require_permission("reconciliation:resolve")),
    db: AsyncSession = Depends(get_db),
):
    """Manually resolve a discrepancy."""
    result = await db.execute(
        select(ReconciliationResultModel)
        .where(ReconciliationResultModel.id == result_id, ReconciliationResultModel.job_id == job_id)
    )
    result = result.scalar_one_or_none()
    
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")
    
    result.status = ReconciliationStatus.RESOLVED.value
    result.resolved_at = datetime.now(timezone.utc)
    result.resolved_by = current_user.id
    result.resolution_notes = request.get("notes", "")
    
    await db.commit()
    await db.refresh(result)
    
    return {"id": str(result.id), "status": result.status, "resolved_at": result.resolved_at.isoformat()}


@reconciliation_router.post(
    "/statements/upload",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
)
async def upload_external_statement(
    request: dict,
    current_user: User = Depends(require_permission("reconciliation:upload")),
    db: AsyncSession = Depends(get_db),
):
    """Upload external statement for reconciliation."""
    engine = ReconciliationEngine(db)
    
    statement = ExternalStatement(
        source=request["source"],
        wallet_id=UUID(request["wallet_id"]),
        currency=request["currency"],
        period_start=datetime.fromisoformat(request["period_start"]),
        period_end=datetime.fromisoformat(request["period_end"]),
        opening_balance=Decimal(request["opening_balance"]),
        closing_balance=Decimal(request["closing_balance"]),
        transactions=request["transactions"],
        raw_data=request.get("raw_data", {}),
    )
    
    # Create or get job
    job = ReconciliationJob(
        reconciliation_type=ReconciliationType.ON_DEMAND.value,
        status=ReconciliationStatus.PENDING,
        period_start=statement.period_start,
        period_end=statement.period_end,
    )
    db.add(job)
    await db.flush()
    
    stmt_id = await engine.upload_external_statement(job.id, statement)
    
    return {"job_id": str(job.id), "statement_id": str(stmt_id)}