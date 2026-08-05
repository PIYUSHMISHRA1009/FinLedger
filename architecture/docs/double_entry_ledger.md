# FinLedger Double-Entry Ledger Implementation

## Overview

The ledger is the foundational layer of FinLedger — an immutable, ACID-compliant double-entry accounting engine that serves as the single source of truth for all financial movements. Every transaction creates balanced debit/credit entries that maintain the fundamental accounting equation: **Assets = Liabilities + Equity**.

## Core Principles

```mermaid
flowchart TD
    A[Double-Entry Principle] --> B[Every Transaction\nHas ≥2 Entries]
    A --> C[Debits = Credits\nAlways Balanced]
    A --> D[Account Normality\nEnforced]
    A --> E[Immutable\nAppend-Only]
    A --> F[Point-in-Time\nConsistency]
    
    B --> G[DEBIT entries\nIncrease Assets/Expenses\nDecrease Liabilities/Equity/Revenue]
    C --> H[Sum(DEBIT) = Sum(CREDIT)\nPer Transaction]
    D --> I[DEBIT-normal: Assets, Expenses\nCREDIT-normal: Liabilities, Equity, Revenue]
    E --> J[No UPDATE/DELETE\non ledger_entries]
    F --> K[MVCC + Versioning\nBalance at any timestamp]
```

## Chart of Accounts Design

### Account Types & Normality

| Account Type | Normality | Increases With | Examples |
|--------------|-----------|----------------|----------|
| **ASSET** | DEBIT | Debit | Cash, Receivables, Customer Wallets |
| **LIABILITY** | CREDIT | Credit | Customer Liabilities, Payables |
| **EQUITY** | CREDIT | Credit | Retained Earnings, Capital |
| **REVENUE** | CREDIT | Credit | Transaction Fees, Interest Income |
| **EXPENSE** | DEBIT | Debit | Processing Fees, Fraud Losses |

### Standard Financial Services Chart of Accounts

```
1000  ASSETS
├── 1010  Customer Wallets - USD (DEBIT)
├── 1011  Customer Wallets - EUR (DEBIT)
├── 1012  Customer Wallets - GBP (DEBIT)
├── 1020  Operating Bank Accounts (DEBIT)
├── 1030  Settlement Accounts (DEBIT)
├── 1040  Receivables (DEBIT)
└── 1050  Prepaid Expenses (DEBIT)

2000  LIABILITIES
├── 2010  Customer Liabilities - USD (CREDIT)
├── 2011  Customer Liabilities - EUR (CREDIT)
├── 2012  Customer Liabilities - GBP (CREDIT)
├── 2020  Accounts Payable (CREDIT)
├── 2030  Accrued Expenses (CREDIT)
├── 2040  Deferred Revenue (CREDIT)
└── 2050  Settlement Payables (CREDIT)

3000  EQUITY
├── 3010  Fee Revenue (CREDIT)
├── 3020  Interest Income (CREDIT)
└── 3030  Platform Equity (CREDIT)

4000  REVENUE
├── 4010  Transaction Fees (CREDIT)
├── 4020  Transfer Fees (CREDIT)
├── 4030  Deposit Fees (CREDIT)
├── 4040  Withdrawal Fees (CREDIT)
├── 4050  FX Spread Revenue (CREDIT)
└── 4060  Interest Revenue (CREDIT)

5000  EXPENSES
├── 5010  Payment Processing Fees (DEBIT)
├── 5020  Bank Fees (DEBIT)
├── 5030  Network Fees (DEBIT)
├── 5040  Fraud Losses (DEBIT)
└── 5050  Operational Expenses (DEBIT)
```

## Ledger Entry Structure

```python
class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    ledger_transaction_id: Mapped[UUID] = mapped_column(
        ForeignKey("ledger_transactions.id", ondelete="CASCADE"),
        index=True
    )
    ledger_account_id: Mapped[UUID] = mapped_column(
        ForeignKey("ledger_accounts.id", ondelete="RESTRICT"),
        index=True
    )
    entry_type: Mapped[LedgerEntryType]  # DEBIT or CREDIT
    amount: Mapped[Decimal] = mapped_column(Numeric(19, 4))  # 4 decimal places
    description: Mapped[str | None]
    sequence: Mapped[int]  # Order within transaction
    metadata: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=func.now())
```

## Transaction Examples

### 1. Customer Deposit ($100 USD)

**Business Event**: Customer deposits $100 from external bank

```
┌─────────────────────────────────────────────────────────────┐
│  LEDGER TRANSACTION: DEP-20240115-001                       │
│  Description: Customer deposit from external bank           │
├──────────────┬──────────────────────┬─────────┬─────────────┤
│  Account     │  Name                │  Type   │  Amount     │
├──────────────┼──────────────────────┼─────────┼─────────────┤
│  1030        │  Settlement Account  │  DEBIT  │  100.00     │
│  2010        │  Customer Liab - USD │  CREDIT │  100.00     │
├──────────────┼──────────────────────┼─────────┼─────────────┤
│  TOTAL       │                      │         │  100.00     │
│              │                      │  DEBIT  │  100.00     │
│              │                      │  CREDIT │  100.00     │
└──────────────┴──────────────────────┴─────────┴─────────────┘
```

**Wallet Balance Impact** (Customer Wallet - USD):
- Posted Balance: +$100 (liability increased = customer can spend more)
- Available Balance: +$100 (funds available immediately)

### 2. Wallet-to-Wallet Transfer ($25 USD)

**Business Event**: Alice (Wallet A) sends $25 to Bob (Wallet B)

```
┌─────────────────────────────────────────────────────────────┐
│  LEDGER TRANSACTION: XFR-20240115-042                       │
│  Description: Transfer from Alice to Bob                    │
├──────────────┬──────────────────────┬─────────┬─────────────┤
│  Account     │  Name                │  Type   │  Amount     │
├──────────────┼──────────────────────┼─────────┼─────────────┤
│  2010        │  Customer Liab - USD │  DEBIT  │  25.00      │  (Alice)
│  2010        │  Customer Liab - USD │  CREDIT │  25.00      │  (Bob)
├──────────────┼──────────────────────┼─────────┼─────────────┤
│  TOTAL       │                      │         │  25.00      │
│              │                      │  DEBIT  │  25.00      │
│              │                      │  CREDIT │  25.00      │
└──────────────┴──────────────────────┴─────────┴─────────────┘
```

**Wallet Balance Impact**:
- Alice: Posted -$25, Available -$25 (liability decreased)
- Bob: Posted +$25, Available +$25 (liability increased)

### 3. Platform Fee Collection ($2.50)

**Business Event**: Platform charges 1% fee on $250 transfer

```
┌─────────────────────────────────────────────────────────────┐
│  LEDGER TRANSACTION: FEE-20240115-018                       │
│  Description: Platform fee on transfer                      │
├──────────────┬──────────────────────┬─────────┬─────────────┤
│  Account     │  Name                │  Type   │  Amount     │
├──────────────┼──────────────────────┼─────────┼─────────────┤
│  2010        │  Customer Liab - USD │  DEBIT  │  2.50       │
│  4010        │  Transaction Fees    │  CREDIT │  2.50       │
├──────────────┼──────────────────────┼─────────┼─────────────┤
│  TOTAL       │                      │         │  2.50       │
│              │                      │  DEBIT  │  2.50       │
│              │                      │  CREDIT │  2.50       │
└──────────────┴──────────────────────┴─────────┴─────────────┘
```

### 4. Withdrawal to External Bank ($500)

**Business Event**: Customer withdraws $500 to external bank

```
┌─────────────────────────────────────────────────────────────┐
│  LEDGER TRANSACTION: WDR-20240115-009                       │
│  Description: Customer withdrawal to external bank          │
├──────────────┬──────────────────────┬─────────┬─────────────┤
│  Account     │  Name                │  Type   │  Amount     │
├──────────────┼──────────────────────┼─────────┼─────────────┤
│  2010        │  Customer Liab - USD │  DEBIT  │  500.00     │
│  1030        │  Settlement Account  │  CREDIT │  500.00     │
├──────────────┼──────────────────────┼─────────┼─────────────┤
│  TOTAL       │                      │         │  500.00     │
│              │                      │  DEBIT  │  500.00     │
│              │                      │  CREDIT │  500.00     │
└──────────────┴──────────────────────┴─────────┴─────────────┘
```

## Ledger Service Implementation

```python
class LedgerService:
    """Core double-entry ledger engine"""
    
    async def create_transaction(
        self,
        reference: str,
        description: str,
        entries: list[LedgerEntrySpec],
        metadata: dict = None
    ) -> LedgerTransaction:
        """
        Create a balanced ledger transaction with entries.
        
        Args:
            reference: Human-readable reference (e.g., "DEP-20240115-001")
            description: Transaction description
            entries: List of {account_code, entry_type, amount, description}
            metadata: Additional context
            
        Returns:
            Created LedgerTransaction with entries
            
        Raises:
            ValidationError: If entries don't balance
            AccountError: If account not found or inactive
        """
        # 1. Validate entries balance
        self._validate_balanced(entries)
        
        # 2. Resolve account codes to IDs
        account_ids = await self._resolve_accounts(entries)
        
        # 3. Create transaction header
        txn = LedgerTransaction(
            reference=reference,
            description=description,
            status=LedgerTxnStatus.POSTED,
            posted_at=datetime.utcnow(),
            metadata=metadata or {}
        )
        self.session.add(txn)
        await self.session.flush()  # Get txn.id
        
        # 4. Create entries with sequence
        for i, entry_spec in enumerate(entries):
            entry = LedgerEntry(
                ledger_transaction_id=txn.id,
                ledger_account_id=account_ids[entry_spec.account_code],
                entry_type=entry_spec.entry_type,
                amount=entry_spec.amount,
                description=entry_spec.description,
                sequence=i
            )
            self.session.add(entry)
        
        # 5. Update materialized balances (single DB transaction)
        await self._update_balances(txn.id, entries, account_ids)
        
        await self.session.commit()
        return txn
    
    def _validate_balanced(self, entries: list[LedgerEntrySpec]):
        """Ensure debits = credits"""
        debits = sum(e.amount for e in entries if e.entry_type == LedgerEntryType.DEBIT)
        credits = sum(e.amount for e in entries if e.entry_type == LedgerEntryType.CREDIT)
        
        if debits != credits:
            raise ValidationError(
                f"Transaction not balanced: debits={debits}, credits={credits}"
            )
        
        if len(entries) < 2:
            raise ValidationError("Transaction must have at least 2 entries")
    
    async def _update_balances(
        self, 
        txn_id: UUID, 
        entries: list[LedgerEntrySpec],
        account_ids: dict[str, UUID]
    ):
        """Update materialized account_balances table"""
        for entry_spec in entries:
            account_id = account_ids[entry_spec.account_code]
            amount = entry_spec.amount
            is_debit = entry_spec.entry_type == LedgerEntryType.DEBIT
            
            # Get account normality
            account = await self.session.get(LedgerAccount, account_id)
            
            # Determine balance impact based on normality
            # For DEBIT-normal accounts: DEBIT increases, CREDIT decreases
            # For CREDIT-normal accounts: CREDIT increases, DEBIT decreases
            if account.normality == AccountNormality.DEBIT:
                posted_delta = amount if is_debit else -amount
                pending_delta = amount  # All entries affect pending
                available_delta = amount if is_debit else 0  # Conservative
            else:  # CREDIT-normal
                posted_delta = -amount if is_debit else amount
                pending_delta = -amount
                available_delta = 0 if is_debit else -amount
            
            # Upsert balance with optimistic locking
            await self.session.execute(
                """
                INSERT INTO account_balances (ledger_account_id, wallet_id, posted_balance, pending_balance, available_balance, version, last_transaction_id)
                VALUES (:account_id, NULL, :posted, :pending, :available, 1, :txn_id)
                ON CONFLICT (ledger_account_id, wallet_id) DO UPDATE SET
                    posted_balance = account_balances.posted_balance + :posted_delta,
                    pending_balance = account_balances.pending_balance + :pending_delta,
                    available_balance = account_balances.available_balance + :available_delta,
                    version = account_balances.version + 1,
                    last_transaction_id = :txn_id,
                    updated_at = NOW()
                WHERE account_balances.version = :expected_version
                """,
                {
                    "account_id": account_id,
                    "txn_id": txn_id,
                    "posted_delta": posted_delta,
                    "pending_delta": pending_delta,
                    "available_delta": available_delta,
                    "expected_version": 0  # Will be overridden by actual version
                }
            )
```

## Balance Computation

### Three Balance Types (Modern Treasury Pattern)

```python
class BalanceType(Enum):
    POSTED = "posted"      # Only fully settled (POSTED ledger transactions)
    PENDING = "pending"    # Posted + pending (all entries regardless of status)
    AVAILABLE = "available" # Conservative: Posted - pending outflows

class BalanceCalculator:
    """Computes balances from ledger entries"""
    
    async def get_balance(
        self, 
        account_id: UUID, 
        wallet_id: UUID | None = None,
        balance_type: BalanceType = BalanceType.POSTED,
        as_of: datetime | None = None
    ) -> Decimal:
        """
        Get balance for account (optionally filtered by wallet) at point in time.
        """
        query = select(func.sum(
            case(
                (LedgerEntry.entry_type == LedgerEntryType.DEBIT, LedgerEntry.amount),
                else_=-LedgerEntry.amount
            )
        )).join(LedgerTransaction).where(
            LedgerEntry.ledger_account_id == account_id
        )
        
        if wallet_id:
            # Join through wallet-specific logic
            query = query.where(...)  # Implementation depends on mapping
        
        if balance_type == BalanceType.POSTED:
            query = query.where(LedgerTransaction.status == LedgerTxnStatus.POSTED)
        elif balance_type == BalanceType.PENDING:
            pass  # Include all statuses
        elif balance_type == BalanceType.AVAILABLE:
            # Complex: Posted inflows - (Posted + Pending) outflows
            query = self._build_available_balance_query(account_id, wallet_id, as_of)
        
        if as_of:
            query = query.where(LedgerTransaction.posted_at <= as_of)
        
        result = await self.session.scalar(query)
        return result or Decimal("0")
    
    def _build_available_balance_query(self, account_id, wallet_id, as_of):
        """Available = Posted Inflows - (Posted + Pending) Outflows"""
        # This is a simplified version; actual implementation uses CTEs
        pass
```

### Wallet Balance Aggregation

```python
async def get_wallet_balances(wallet_id: UUID) -> WalletBalances:
    """Get all three balance types for a wallet"""
    
    # Query materialized balances (O(1) read)
    balances = await session.execute(
        select(AccountBalances, LedgerAccount)
        .join(LedgerAccount)
        .where(AccountBalances.wallet_id == wallet_id)
    )
    
    posted = Decimal("0")
    pending = Decimal("0")
    available = Decimal("0")
    
    for bal, account in balances:
        if account.account_type == AccountType.ASSET:
            posted += bal.posted_balance
            pending += bal.pending_balance
            available += bal.available_balance
        elif account.account_type == AccountType.LIABILITY:
            # Liabilities: higher balance = more customer funds = lower platform asset
            posted -= bal.posted_balance
            pending -= bal.pending_balance
            available -= bal.available_balance
    
    return WalletBalances(
        posted=posted,
        pending=pending,
        available=available,
        currency=wallet.currency
    )
```

## Concurrency Control

### Optimistic Locking

```python
class AccountBalances(Base):
    __tablename__ = "account_balances"
    
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    ledger_account_id: Mapped[UUID] = mapped_column(ForeignKey("ledger_accounts.id"))
    wallet_id: Mapped[UUID | None] = mapped_column(ForeignKey("wallets.id"))
    posted_balance: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    pending_balance: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    available_balance: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=0)
    version: Mapped[int] = mapped_column(default=1)  # Optimistic lock
    last_transaction_id: Mapped[UUID | None]
    updated_at: Mapped[datetime] = mapped_column(default=func.now(), onupdate=func.now())
    
    __table_args__ = (
        UniqueConstraint("ledger_account_id", "wallet_id"),
        Index("ix_balances_account_wallet", "ledger_account_id", "wallet_id"),
    )

async def update_balance_with_retry(
    self, 
    account_id: UUID, 
    wallet_id: UUID | None,
    posted_delta: Decimal,
    pending_delta: Decimal,
    available_delta: Decimal,
    txn_id: UUID,
    max_retries: int = 3
):
    for attempt in range(max_retries):
        # Read current version
        bal = await self.session.get(AccountBalances, (account_id, wallet_id))
        if not bal:
            bal = AccountBalances(
                ledger_account_id=account_id,
                wallet_id=wallet_id,
                posted_balance=0,
                pending_balance=0,
                available_balance=0,
                version=1
            )
            self.session.add(bal)
            await self.session.flush()
        
        # Attempt update with version check
        result = await self.session.execute(
            update(AccountBalances)
            .where(AccountBalances.ledger_account_id == account_id)
            .where(AccountBalances.wallet_id == wallet_id)
            .where(AccountBalances.version == bal.version)
            .values(
                posted_balance=AccountBalances.posted_balance + posted_delta,
                pending_balance=AccountBalances.pending_balance + pending_delta,
                available_balance=AccountBalances.available_balance + available_delta,
                version=AccountBalances.version + 1,
                last_transaction_id=txn_id,
                updated_at=func.now()
            )
        )
        
        if result.rowcount > 0:
            return  # Success
        
        # Version conflict - retry
        await self.session.rollback()
        await asyncio.sleep(0.01 * (attempt + 1))  # Exponential backoff
    
    raise OptimisticLockError(f"Failed to update balance after {max_retries} retries")
```

## Reconciliation Engine

```python
class ReconciliationEngine:
    """Verifies ledger integrity against external sources"""
    
    async def reconcile_wallet(
        self, 
        wallet_id: UUID, 
        external_balance: Decimal,
        as_of: datetime
    ) -> ReconciliationResult:
        """
        Compare internal ledger balance with external statement.
        """
        internal = await self.balance_calculator.get_balance(
            wallet_id=wallet_id,
            balance_type=BalanceType.POSTED,
            as_of=as_of
        )
        
        difference = internal - external_balance
        
        return ReconciliationResult(
            wallet_id=wallet_id,
            internal_balance=internal,
            external_balance=external_balance,
            difference=difference,
            status=ReconciliationStatus.MATCHED if difference == 0 else ReconciliationStatus.MISMATCH,
            as_of=as_of
        )
    
    async def full_reconciliation(self, as_of: datetime) -> ReconciliationReport:
        """Run reconciliation across all wallets/accounts"""
        # 1. Trial balance (debits = credits globally)
        trial_balance = await self.get_trial_balance(as_of)
        
        # 2. Per-wallet reconciliation
        wallet_results = []
        for wallet in await self.get_active_wallets():
            ext_balance = await self.get_external_balance(wallet.id, as_of)
            result = await self.reconcile_wallet(wallet.id, ext_balance, as_of)
            wallet_results.append(result)
        
        # 3. Materialized view verification
        mv_check = await self.verify_materialized_views(as_of)
        
        return ReconciliationReport(
            as_of=as_of,
            trial_balance=trial_balance,
            wallet_results=wallet_results,
            materialized_views_ok=mv_check,
            generated_at=datetime.utcnow()
        )
```

## Trial Balance

```python
async def get_trial_balance(self, as_of: datetime | None = None) -> TrialBalance:
    """Generate trial balance: all accounts with net balances"""
    
    query = """
        SELECT 
            la.code,
            la.name,
            la.account_type,
            la.normality,
            COALESCE(SUM(CASE WHEN le.entry_type = 'DEBIT' THEN le.amount ELSE 0 END), 0) as total_debits,
            COALESCE(SUM(CASE WHEN le.entry_type = 'CREDIT' THEN le.amount ELSE 0 END), 0) as total_credits
        FROM ledger_accounts la
        LEFT JOIN ledger_entries le ON le.ledger_account_id = la.id
        LEFT JOIN ledger_transactions lt ON lt.id = le.ledger_transaction_id
            AND lt.status = 'POSTED'
        WHERE la.is_active = TRUE
    """
    
    if as_of:
        query += " AND lt.posted_at <= :as_of"
    
    query += " GROUP BY la.id, la.code, la.name, la.account_type, la.normality ORDER BY la.code"
    
    results = await self.session.execute(text(query), {"as_of": as_of} if as_of else {})
    
    accounts = []
    total_debits = Decimal("0")
    total_credits = Decimal("0")
    
    for row in results:
        net = row.total_debits - row.total_credits
        accounts.append(TrialBalanceAccount(
            code=row.code,
            name=row.name,
            account_type=row.account_type,
            normality=row.normality,
            total_debits=row.total_debits,
            total_credits=row.total_credits,
            net_balance=net
        ))
        total_debits += row.total_debits
        total_credits += row.total_credits
    
    return TrialBalance(
        accounts=accounts,
        total_debits=total_debits,
        total_credits=total_credits,
        balanced=(total_debits == total_credits),
        as_of=as_of or datetime.utcnow()
    )
```

## Audit & Compliance

### Immutable Audit Trail

```python
# Every ledger transaction creates audit log
async def _audit_ledger_transaction(txn: LedgerTransaction, entries: list[LedgerEntry]):
    await audit_log(
        action="ledger.transaction.posted",
        resource_type="ledger_transaction",
        resource_id=txn.id,
        new_values={
            "reference": txn.reference,
            "description": txn.description,
            "entries": [
                {
                    "account_code": e.account_code,
                    "entry_type": e.entry_type.value,
                    "amount": str(e.amount)
                }
                for e in entries
            ]
        },
        request_id=get_request_id()
    )
```

### Compliance Features

| Feature | Implementation |
|---------|----------------|
| **Immutability** | No UPDATE/DELETE on ledger_entries; VOIDED status for corrections |
| **Versioning** | Optimistic locking on ledger_transactions and account_balances |
| **Point-in-time** | MVCC + posted_at timestamps enable historical queries |
| **Segregation** | System accounts (is_system_account) cannot be modified by users |
| **Reconciliation** | Daily automated reconciliation job with alerting |
| **Export** | Audit-ready CSV/JSON export for regulators |

## Testing Strategy

### Unit Tests
- [ ] Entry validation (debits = credits)
- [ ] Account normality enforcement
- [ ] Balance computation for all three types
- [ ] Optimistic locking conflict handling
- [ ] Materialized view updates

### Property-Based Tests
- [ ] Random transaction generation always balances
- [ ] Concurrent transfers maintain consistency
- [ ] Balance invariants hold under load

### Integration Tests
- [ ] Full deposit → transfer → withdrawal cycle
- [ ] Reconciliation matches external statements
- [ ] Trial balance always balances
- [ ] Void/reversal creates correct mirror entries

### Load Tests
- [ ] 10,000 TPS sustained ledger writes
- [ ] p99 latency < 50ms for balance reads
- [ ] Optimistic lock contention < 1%

## Performance Optimizations

| Optimization | Technique |
|--------------|-----------|
| **Balance Reads** | Materialized `account_balances` table (O(1)) |
| **Balance Writes** | Batch updates in single transaction |
| **History Queries** | Partitioned `ledger_entries` by month |
| **Trial Balance** | Pre-aggregated daily snapshots |
| **Indexes** | Composite indexes on (account_id, txn_id) INCLUDE (type, amount) |
| **Connection Pool** | PgBouncer for connection reuse |

## Future Enhancements

- [ ] **Multi-currency ledger**: Single ledger with FX rate snapshots
- [ ] **Sub-ledgers**: Hierarchical accounts with rollup balances
- [ ] **Event sourcing**: Full event log for temporal queries
- [ ] **Distributed ledger**: Cross-region replication with CRDTs
- [ ] **Smart contracts**: Programmable ledger rules (Formance Numscript style)