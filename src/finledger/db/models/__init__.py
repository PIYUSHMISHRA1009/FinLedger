"""
FinLedger SQLAlchemy Models

Complete ORM models matching the database schema design.
"""

import enum
from datetime import datetime
from decimal import Decimal
from typing import Optional, List
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from finledger.db.database import Base


# Enum Types
class UserRole(str, enum.Enum):
    USER = "USER"
    ADMIN = "ADMIN"
    COMPLIANCE = "COMPLIANCE"
    SYSTEM = "SYSTEM"


class WalletStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"
    PENDING_VERIFICATION = "PENDING_VERIFICATION"


class TransactionType(str, enum.Enum):
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    TRANSFER_IN = "TRANSFER_IN"
    TRANSFER_OUT = "TRANSFER_OUT"
    FEE = "FEE"
    REVERSAL = "REVERSAL"
    ADJUSTMENT = "ADJUSTMENT"


class TransactionStatus(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    REVERSED = "REVERSED"
    CANCELLED = "CANCELLED"


class AccountType(str, enum.Enum):
    ASSET = "ASSET"
    LIABILITY = "LIABILITY"
    EQUITY = "EQUITY"
    REVENUE = "REVENUE"
    EXPENSE = "EXPENSE"


class AccountNormality(str, enum.Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class LedgerEntryType(str, enum.Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class LedgerTxnStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class FraudRuleType(str, enum.Enum):
    VELOCITY = "VELOCITY"
    AMOUNT_THRESHOLD = "AMOUNT_THRESHOLD"
    COUNTERPARTY_FREQUENCY = "COUNTERPARTY_FREQUENCY"
    SUSPICIOUS_PATTERN = "SUSPICIOUS_PATTERN"
    GEO_VELOCITY = "GEO_VELOCITY"
    ML_SCORE = "ML_SCORE"


class FraudRiskLevel(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class FraudEventStatus(str, enum.Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    BLOCKED = "BLOCKED"
    FALSE_POSITIVE = "FALSE_POSITIVE"
    ESCALATED = "ESCALATED"


# User Model
class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.USER, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    is_verified: Mapped[bool] = mapped_column(default=False, nullable=False)
    email_verification_token: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    email_verification_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    password_reset_token: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    password_reset_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    wallets: Mapped[List["Wallet"]] = relationship("Wallet", back_populates="user", cascade="all, delete-orphan")
    refresh_tokens: Mapped[List["RefreshToken"]] = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")
    fraud_events: Mapped[List["FraudEvent"]] = relationship("FraudEvent", back_populates="user")
    audit_logs: Mapped[List["AuditLog"]] = relationship("AuditLog", back_populates="user")

    __table_args__ = (
        Index("idx_users_role", "role"),
        Index("idx_users_is_active", "is_active", postgresql_where=text("is_active = true")),
    )


# Refresh Token Model
class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    revoked: Mapped[bool] = mapped_column(default=False, nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(INET, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="refresh_tokens")

    __table_args__ = (
        Index("idx_refresh_tokens_user_expires", "user_id", "expires_at", postgresql_where=text("revoked = false")),
    )


# Wallet Model
class Wallet(Base):
    __tablename__ = "wallets"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[WalletStatus] = mapped_column(Enum(WalletStatus), default=WalletStatus.PENDING_VERIFICATION, nullable=False, index=True)
    settings: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="wallets")
    transactions_sent: Mapped[List["Transaction"]] = relationship("Transaction", foreign_keys="Transaction.source_wallet_id", back_populates="source_wallet")
    transactions_received: Mapped[List["Transaction"]] = relationship("Transaction", foreign_keys="Transaction.destination_wallet_id", back_populates="destination_wallet")
    ledger_entries: Mapped[List["LedgerEntry"]] = relationship("LedgerEntry", back_populates="wallet")
    account_balances: Mapped[List["AccountBalance"]] = relationship("AccountBalance", back_populates="wallet")

    __table_args__ = (
        CheckConstraint("LENGTH(currency) = 3", name="chk_currency_length"),
        UniqueConstraint("user_id", "currency", "name", name="uq_wallet_user_currency_name", postgresql_where=text("status IN ('ACTIVE', 'PENDING_VERIFICATION')")),
        Index("idx_wallets_currency", "currency"),
    )


# Transaction Model
class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    source_wallet_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("wallets.id", ondelete="SET NULL"), nullable=True, index=True)
    destination_wallet_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("wallets.id", ondelete="SET NULL"), nullable=True, index=True)
    ledger_transaction_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("ledger_transactions.id", ondelete="SET NULL"), nullable=True, index=True)
    type: Mapped[TransactionType] = mapped_column(Enum(TransactionType), nullable=False, index=True)
    status: Mapped[TransactionStatus] = mapped_column(Enum(TransactionStatus), default=TransactionStatus.PENDING, nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    failure_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    failure_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_retries: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    source_wallet: Mapped[Optional["Wallet"]] = relationship("Wallet", foreign_keys=[source_wallet_id], back_populates="transactions_sent")
    destination_wallet: Mapped[Optional["Wallet"]] = relationship("Wallet", foreign_keys=[destination_wallet_id], back_populates="transactions_received")
    ledger_transaction: Mapped[Optional["LedgerTransaction"]] = relationship("LedgerTransaction", back_populates="transactions")
    fraud_events: Mapped[List["FraudEvent"]] = relationship("FraudEvent", back_populates="transaction")
    idempotency_key_record: Mapped[Optional["IdempotencyKey"]] = relationship("IdempotencyKey", back_populates="transaction")

    __table_args__ = (
        CheckConstraint("amount > 0", name="chk_amount_positive"),
        CheckConstraint("LENGTH(currency) = 3", name="chk_currency_length"),
        CheckConstraint(
            "source_wallet_id IS NULL OR destination_wallet_id IS NULL OR source_wallet_id != destination_wallet_id",
            name="chk_wallets_different",
        ),
        Index("idx_transactions_wallet_created", "source_wallet_id", "created_at", postgresql_include=["type", "amount", "status", "description"]),
    )


# Ledger Account Model
class LedgerAccount(Base):
    __tablename__ = "ledger_accounts"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    account_type: Mapped[AccountType] = mapped_column(Enum(AccountType), nullable=False, index=True)
    normality: Mapped[AccountNormality] = mapped_column(Enum(AccountNormality), nullable=False)
    parent_account_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("ledger_accounts.id", ondelete="SET NULL"), nullable=True, index=True)
    currency: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False, index=True)
    is_system_account: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    parent: Mapped[Optional["LedgerAccount"]] = relationship("LedgerAccount", remote_side=[id], backref="children")
    entries: Mapped[List["LedgerEntry"]] = relationship("LedgerEntry", back_populates="account")
    balances: Mapped[List["AccountBalance"]] = relationship("AccountBalance", back_populates="account")

    __table_args__ = (
        CheckConstraint("currency IS NULL OR LENGTH(currency) = 3", name="chk_currency_length"),
        Index("idx_ledger_accounts_parent", "parent_account_id"),
        Index("idx_ledger_accounts_active", "is_active", postgresql_where=text("is_active = true")),
    )


# Ledger Transaction Model
class LedgerTransaction(Base):
    __tablename__ = "ledger_transactions"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    reference: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[LedgerTxnStatus] = mapped_column(Enum(LedgerTxnStatus), default=LedgerTxnStatus.DRAFT, nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    voided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    voided_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    entries: Mapped[List["LedgerEntry"]] = relationship("LedgerEntry", back_populates="transaction", cascade="all, delete-orphan")
    transactions: Mapped[List["Transaction"]] = relationship("Transaction", back_populates="ledger_transaction")

    __table_args__ = (
        Index("idx_ledger_transactions_posted", "posted_at", postgresql_where=text("status = 'POSTED'")),
    )


# Ledger Entry Model
class LedgerEntry(Base):
    __tablename__ = "ledger_entries"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    ledger_transaction_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("ledger_transactions.id", ondelete="CASCADE"), nullable=False, index=True)
    ledger_account_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("ledger_accounts.id", ondelete="RESTRICT"), nullable=False, index=True)
    wallet_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("wallets.id", ondelete="CASCADE"), nullable=True, index=True)
    entry_type: Mapped[LedgerEntryType] = mapped_column(Enum(LedgerEntryType), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    transaction: Mapped["LedgerTransaction"] = relationship("LedgerTransaction", back_populates="entries")
    account: Mapped["LedgerAccount"] = relationship("LedgerAccount", back_populates="entries")
    wallet: Mapped[Optional["Wallet"]] = relationship("Wallet", back_populates="ledger_entries")

    __table_args__ = (
        CheckConstraint("amount > 0", name="chk_amount_positive"),
        Index("idx_ledger_entries_txn_account", "ledger_transaction_id", "ledger_account_id", postgresql_include=["entry_type", "amount"]),
    )


# Account Balance Model (Materialized View)
class AccountBalance(Base):
    __tablename__ = "account_balances"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    ledger_account_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("ledger_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    wallet_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("wallets.id", ondelete="CASCADE"), nullable=True, index=True)
    posted_balance: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=Decimal("0"), nullable=False)
    pending_balance: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=Decimal("0"), nullable=False)
    available_balance: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=Decimal("0"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    last_transaction_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    account: Mapped["LedgerAccount"] = relationship("LedgerAccount", back_populates="balances")
    wallet: Mapped[Optional["Wallet"]] = relationship("Wallet", back_populates="account_balances")

    __table_args__ = (
        UniqueConstraint("ledger_account_id", "wallet_id", name="uq_account_wallet"),
    )


# Fraud Rule Model
class FraudRule(Base):
    __tablename__ = "fraud_rules"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rule_type: Mapped[FraudRuleType] = mapped_column(Enum(FraudRuleType), nullable=False)
    weight: Mapped[Decimal] = mapped_column(Numeric(4, 3), default=Decimal("0.100"), nullable=False)
    parameters: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    active: Mapped[bool] = mapped_column(default=True, nullable=False, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    fraud_events: Mapped[List["FraudEvent"]] = relationship("FraudEvent", back_populates="triggered_rules")

    __table_args__ = (
        Index("idx_fraud_rules_active", "active", postgresql_where=text("active = true")),
        Index("idx_fraud_rules_priority", "priority"),
    )


# Fraud Event Model
class FraudEvent(Base):
    __tablename__ = "fraud_events"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    transaction_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    wallet_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("wallets.id", ondelete="CASCADE"), nullable=False, index=True)
    risk_score: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    risk_level: Mapped[FraudRiskLevel] = mapped_column(Enum(FraudRiskLevel), nullable=False, index=True)
    triggered_rules: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)  # Array of {rule_id, rule_code, weight, triggered}
    status: Mapped[FraudEventStatus] = mapped_column(Enum(FraudEventStatus), default=FraudEventStatus.PENDING_REVIEW, nullable=False, index=True)
    reviewer_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    review_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    auto_blocked: Mapped[bool] = mapped_column(default=False, nullable=False)
    ml_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(4, 3), nullable=True)
    ml_model_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    transaction: Mapped["Transaction"] = relationship("Transaction", back_populates="fraud_events")
    user: Mapped["User"] = relationship("User", back_populates="fraud_events")
    wallet: Mapped["Wallet"] = relationship("Wallet")
    reviewer: Mapped[Optional["User"]] = relationship("User", foreign_keys=[reviewer_id])

    __table_args__ = (
        Index("idx_fraud_events_review_queue", "risk_level", "status", "created_at", postgresql_where=text("status = 'PENDING_REVIEW'")),
        Index("idx_fraud_events_user_recent", "user_id", "created_at"),
    )


# Idempotency Key Model
class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    transaction_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True, index=True)
    request_method: Mapped[str] = mapped_column(String(10), nullable=False)
    request_path: Mapped[str] = mapped_column(String(500), nullable=False)
    request_body: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    response_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    response_body: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    transaction: Mapped[Optional["Transaction"]] = relationship("Transaction", back_populates="idempotency_key_record")

    __table_args__ = (
        Index("idx_idempotency_keys_expires", "expires_at"),
    )


# Audit Log Model
class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    old_values: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    new_values: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(INET, nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    request_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    # Relationships
    user: Mapped[Optional["User"]] = relationship("User", back_populates="audit_logs")

    __table_args__ = (
        Index("idx_audit_logs_resource", "resource_type", "resource_id", "created_at"),
        Index("idx_audit_logs_request", "request_id"),
    )