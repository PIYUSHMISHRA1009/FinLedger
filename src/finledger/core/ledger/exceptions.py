"""
FinLedger Custom Exceptions

Domain-specific exceptions for the ledger and financial services.
"""


class FinLedgerError(Exception):
    """Base exception for FinLedger."""
    
    def __init__(self, message: str, code: str = None, details: dict = None):
        super().__init__(message)
        self.message = message
        self.code = code or self.__class__.__name__
        self.details = details or {}


# Ledger Exceptions
class LedgerError(FinLedgerError):
    """Base ledger exception."""
    pass


class LedgerValidationError(LedgerError):
    """Raised when ledger validation fails."""
    pass


class LedgerImbalanceError(LedgerError):
    """Raised when transaction debits don't equal credits."""
    pass


class AccountNotFoundError(LedgerError):
    """Raised when ledger account is not found."""
    pass


class InsufficientBalanceError(LedgerError):
    """Raised when available balance is insufficient."""
    pass


class OptimisticLockError(LedgerError):
    """Raised when optimistic locking conflict occurs."""
    pass


# Wallet Exceptions
class WalletError(FinLedgerError):
    """Base wallet exception."""
    pass


class WalletNotFoundError(WalletError):
    """Raised when wallet is not found."""
    pass


class WalletFrozenError(WalletError):
    """Raised when wallet is frozen."""
    pass


class WalletClosedError(WalletError):
    """Raised when wallet is closed."""
    pass


class InsufficientFundsError(WalletError):
    """Raised when wallet has insufficient funds."""
    pass


class CurrencyMismatchError(WalletError):
    """Raised when currencies don't match."""
    pass


class SameWalletTransferError(WalletError):
    """Raised when attempting to transfer to same wallet."""
    pass


# Transaction Exceptions
class TransactionError(FinLedgerError):
    """Base transaction exception."""
    pass


class TransactionNotFoundError(TransactionError):
    """Raised when transaction is not found."""
    pass


class TransactionFailedError(TransactionError):
    """Raised when transaction fails."""
    pass


class IdempotencyError(TransactionError):
    """Raised when idempotency key conflict occurs."""
    pass


class IdempotencyKeyRequiredError(IdempotencyError):
    """Raised when idempotency key is required but missing."""
    pass


class IdempotencyKeyConflictError(IdempotencyError):
    """Raised when same idempotency key used with different request."""
    pass


# Fraud Exceptions
class FraudError(FinLedgerError):
    """Base fraud exception."""
    pass


class FraudBlockedError(FraudError):
    """Raised when transaction is blocked by fraud engine."""
    pass


class FraudRuleError(FraudError):
    """Raised when fraud rule configuration is invalid."""
    pass


# Authentication Exceptions
class AuthError(FinLedgerError):
    """Base authentication exception."""
    pass


class InvalidCredentialsError(AuthError):
    """Raised when credentials are invalid."""
    pass


class AccountLockedError(AuthError):
    """Raised when account is locked."""
    pass


class AccountDeactivatedError(AuthError):
    """Raised when account is deactivated."""
    pass


class TokenExpiredError(AuthError):
    """Raised when token is expired."""
    pass


class TokenRevokedError(AuthError):
    """Raised when token is revoked."""
    pass


class TokenReuseError(AuthError):
    """Raised when refresh token reuse is detected."""
    pass


class InvalidTokenError(AuthError):
    """Raised when token is invalid."""
    pass


# Permission Exceptions
class PermissionError(FinLedgerError):
    """Raised when permission check fails."""
    pass


class InsufficientPermissionsError(PermissionError):
    """Raised when user lacks required permission."""
    pass


# Rate Limiting Exceptions
class RateLimitError(FinLedgerError):
    """Raised when rate limit is exceeded."""
    pass


# Validation Exceptions
class ValidationError(FinLedgerError):
    """Raised when input validation fails."""
    pass


class PasswordStrengthError(ValidationError):
    """Raised when password doesn't meet strength requirements."""
    pass