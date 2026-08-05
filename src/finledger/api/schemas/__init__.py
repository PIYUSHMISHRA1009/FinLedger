"""
FinLedger API Schemas (Pydantic Models)

Request/Response models for all API endpoints.
"""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional, Dict, Any
from uuid import UUID
from enum import Enum

from pydantic import BaseModel, Field, EmailStr, field_validator, ConfigDict


# Enums
class UserRole(str, Enum):
    USER = "USER"
    ADMIN = "ADMIN"
    COMPLIANCE = "COMPLIANCE"
    SYSTEM = "SYSTEM"


class WalletStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"
    PENDING_VERIFICATION = "PENDING_VERIFICATION"


class TransactionType(str, Enum):
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    TRANSFER_IN = "TRANSFER_IN"
    TRANSFER_OUT = "TRANSFER_OUT"
    FEE = "FEE"
    REVERSAL = "REVERSAL"
    ADJUSTMENT = "ADJUSTMENT"


class TransactionStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    REVERSED = "REVERSED"
    CANCELLED = "CANCELLED"


class AccountType(str, Enum):
    ASSET = "ASSET"
    LIABILITY = "LIABILITY"
    EQUITY = "EQUITY"
    REVENUE = "REVENUE"
    EXPENSE = "EXPENSE"


class AccountNormality(str, Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class LedgerEntryType(str, Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class LedgerTxnStatus(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class FraudRuleType(str, Enum):
    VELOCITY = "VELOCITY"
    AMOUNT_THRESHOLD = "AMOUNT_THRESHOLD"
    COUNTERPARTY_FREQUENCY = "COUNTERPARTY_FREQUENCY"
    SUSPICIOUS_PATTERN = "SUSPICIOUS_PATTERN"
    GEO_VELOCITY = "GEO_VELOCITY"
    ML_SCORE = "ML_SCORE"


class FraudRiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class FraudEventStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    BLOCKED = "BLOCKED"
    FALSE_POSITIVE = "FALSE_POSITIVE"
    ESCALATED = "ESCALATED"


# Base Models
class BaseSchema(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        json_encoders={
            Decimal: lambda v: str(v),
            datetime: lambda v: v.isoformat(),
            UUID: lambda v: str(v),
        },
    )


# Pagination
class PaginationParams(BaseModel):
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class PaginatedResponse(BaseSchema):
    items: List[Any]
    total: int
    limit: int
    offset: int


# Error Responses
class ErrorDetail(BaseModel):
    field: Optional[str] = None
    message: str


class ErrorResponse(BaseModel):
    error: "ErrorBody"


class ErrorBody(BaseModel):
    code: str
    message: str
    details: List[ErrorDetail] = []
    request_id: Optional[str] = None


# Health
class HealthResponse(BaseSchema):
    status: str
    version: str
    timestamp: datetime


class HealthDetail(BaseSchema):
    status: str
    checks: Dict[str, str]


# Authentication
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=12)
    full_name: str = Field(..., min_length=1, max_length=255)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseSchema):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class UserResponse(BaseSchema):
    id: UUID
    email: EmailStr
    full_name: str
    role: UserRole
    is_active: bool
    is_verified: bool
    last_login_at: Optional[datetime] = None
    created_at: datetime


# Wallet
class WalletCreateRequest(BaseModel):
    currency: str = Field(..., min_length=3, max_length=3)
    name: str = Field(..., min_length=1, max_length=255)

    @field_validator("currency")
    @classmethod
    def currency_upper(cls, v: str) -> str:
        return v.upper()


class WalletUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    status: Optional[WalletStatus] = None


class WalletResponse(BaseSchema):
    id: UUID
    user_id: UUID
    currency: str
    name: str
    status: WalletStatus
    settings: Dict[str, Any] = {}
    created_at: datetime
    updated_at: datetime
    closed_at: Optional[datetime] = None


class WalletBalanceResponse(BaseSchema):
    wallet_id: UUID
    currency: str
    posted_balance: str
    pending_balance: str
    available_balance: str
    as_of: datetime


# Transactions
class DepositRequest(BaseModel):
    amount: Decimal = Field(..., gt=0, decimal_places=4)
    description: str = Field(..., min_length=1, max_length=500)
    metadata: Optional[Dict[str, Any]] = {}


class WithdrawalRequest(BaseModel):
    amount: Decimal = Field(..., gt=0, decimal_places=4)
    description: str = Field(..., min_length=1, max_length=500)
    metadata: Optional[Dict[str, Any]] = {}


class TransferRequest(BaseModel):
    amount: Decimal = Field(..., gt=0, decimal_places=4)
    destination_wallet_id: UUID
    description: str = Field(..., min_length=1, max_length=500)
    metadata: Optional[Dict[str, Any]] = {}


class TransactionResponse(BaseSchema):
    id: UUID
    type: TransactionType
    status: TransactionStatus
    amount: str
    currency: str
    description: Optional[str] = None
    source_wallet_id: Optional[UUID] = None
    destination_wallet_id: Optional[UUID] = None
    counterparty_wallet_id: Optional[UUID] = None
    counterparty_name: Optional[str] = None
    fraud_risk_score: Optional[str] = None
    fraud_risk_level: Optional[FraudRiskLevel] = None
    created_at: datetime
    completed_at: Optional[datetime] = None


class TransactionListParams(PaginationParams):
    type: Optional[str] = None
    status: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None


# Ledger
class LedgerAccountResponse(BaseSchema):
    id: UUID
    code: str
    name: str
    account_type: AccountType
    normality: AccountNormality
    currency: Optional[str] = None
    is_active: bool
    is_system_account: bool


class LedgerEntryResponse(BaseSchema):
    id: UUID
    account_id: UUID
    account_code: str
    account_name: str
    entry_type: LedgerEntryType
    amount: str


class LedgerTransactionResponse(BaseSchema):
    id: UUID
    reference: str
    description: str
    status: LedgerTxnStatus
    version: int
    posted_at: Optional[datetime] = None
    entries: List[LedgerEntryResponse] = []
    created_at: datetime


class LedgerTransactionListParams(PaginationParams):
    wallet_id: Optional[UUID] = None
    account_id: Optional[UUID] = None
    status: Optional[str] = None


class AccountBalanceResponse(BaseSchema):
    account_id: UUID
    account_code: str
    wallet_id: Optional[UUID] = None
    posted_balance: str
    pending_balance: str
    available_balance: str
    as_of: datetime


class TrialBalanceResponse(BaseSchema):
    as_of: datetime
    accounts: List[Dict[str, Any]]
    total_debits: str
    total_credits: str
    balanced: bool


# Fraud
class FraudEventResponse(BaseSchema):
    id: UUID
    transaction_id: UUID
    user_id: UUID
    wallet_id: UUID
    risk_score: str
    risk_level: FraudRiskLevel
    triggered_rules: List[Dict[str, Any]]
    status: FraudEventStatus
    reviewer_id: Optional[UUID] = None
    reviewed_at: Optional[datetime] = None
    review_notes: Optional[str] = None
    auto_blocked: bool
    created_at: datetime


class FraudReviewRequest(BaseModel):
    status: FraudEventStatus
    review_notes: Optional[str] = None


class FraudRuleCreateRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    rule_type: FraudRuleType
    weight: Decimal = Field(..., ge=0, le=1, decimal_places=3)
    parameters: Dict[str, Any] = {}
    active: bool = True
    priority: int = Field(default=100, ge=0)


class FraudRuleUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    weight: Optional[Decimal] = Field(None, ge=0, le=1, decimal_places=3)
    parameters: Optional[Dict[str, Any]] = None
    active: Optional[bool] = None
    priority: Optional[int] = None


class FraudRuleResponse(BaseSchema):
    id: UUID
    code: str
    name: str
    description: Optional[str] = None
    rule_type: FraudRuleType
    weight: str
    parameters: Dict[str, Any]
    active: bool
    priority: int
    created_at: datetime
    updated_at: datetime


# Admin
class AdminUserUpdateRequest(BaseModel):
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None
    is_verified: Optional[bool] = None


class AdminStatsResponse(BaseSchema):
    total_users: int
    total_wallets: int
    total_transactions: int
    total_volume: str
    pending_fraud_reviews: int