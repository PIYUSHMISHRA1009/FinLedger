"""
FinLedger Unit Tests - Wallet Service
"""

import pytest
from decimal import Decimal
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from finledger.core.wallet.service import WalletService, WalletBalance, TransferResult
from finledger.core.wallet.exceptions import (
    InsufficientFundsError,
    WalletNotFoundError,
    WalletFrozenError,
    WalletClosedError,
    CurrencyMismatchError,
    SameWalletTransferError,
    ValidationError,
)
from finledger.core.ledger.service import LedgerService, LedgerEntrySpec, LedgerEntryType, BalanceResult
from finledger.core.fraud.service import FraudService, FraudAssessment
from finledger.core.fraud.exceptions import FraudError
from finledger.db.models import (
    Wallet,
    Transaction,
    TransactionType,
    TransactionStatus,
    WalletStatus,
    LedgerAccount,
    AccountType,
    AccountNormality,
)
from sqlalchemy.ext.asyncio import AsyncSession


class TestWalletService:
    """Tests for WalletService."""
    
    @pytest.fixture
    def mock_db(self):
        return AsyncMock()
    
    @pytest.fixture
    def mock_ledger(self):
        return AsyncMock(spec=LedgerService)
    
    @pytest.fixture
    def mock_fraud(self):
        return AsyncMock(spec=FraudService)
    
    @pytest.fixture
    def wallet_service(self, mock_db, mock_ledger, mock_fraud):
        return WalletService(mock_db, mock_ledger, mock_fraud)
    
    @pytest.fixture
    def sample_user_id(self):
        return uuid4()
    
    @pytest.fixture
    def sample_wallet(self, sample_user_id):
        return Wallet(
            id=uuid4(),
            user_id=sample_user_id,
            currency="USD",
            name="Test Wallet",
            status=WalletStatus.ACTIVE,
        )
    
    @pytest.fixture
    def sample_liability_account(self):
        return LedgerAccount(
            id=uuid4(),
            code="2010",
            name="Customer Liabilities - USD",
            account_type="LIABILITY",
            normality="CREDIT",
            is_active=True,
        )
    
    @pytest.fixture
    def sample_settlement_account(self):
        return LedgerAccount(
            id=uuid4(),
            code="1030",
            name="Settlement Accounts",
            account_type="ASSET",
            normality="DEBIT",
            is_active=True,
        )
    
    @pytest.mark.asyncio
    async def test_create_wallet_success(self, wallet_service, mock_db, sample_user_id):
        mock_db.execute.return_value.scalar_one_or_none.return_value = None
        
        wallet = await wallet_service.create_wallet(
            user_id=sample_user_id,
            currency="USD",
            name="Test Wallet",
        )
        
        assert wallet.user_id == sample_user_id
        assert wallet.currency == "USD"
        assert wallet.name == "Test Wallet"
        assert wallet.status == WalletStatus.ACTIVE
        mock_db.add.assert_called_once()
        mock_db.flush.assert_called_once()
        mock_db.refresh.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_create_wallet_duplicate(self, wallet_service, mock_db, sample_user_id):
        existing_wallet = Wallet(id=uuid4(), user_id=sample_user_id, currency="USD", name="Test")
        mock_db.execute.return_value.scalar_one_or_none.return_value = existing_wallet
        
        with pytest.raises(ValidationError, match="already exists"):
            await wallet_service.create_wallet(
                user_id=sample_user_id,
                currency="USD",
                name="Test",
            )
    
    @pytest.mark.asyncio
    async def test_create_wallet_invalid_currency(self, wallet_service, sample_user_id):
        with pytest.raises(ValidationError, match="3 characters"):
            await wallet_service.create_wallet(
                user_id=sample_user_id,
                currency="US",
                name="Test",
            )
    
    @pytest.mark.asyncio
    async def test_get_wallet_success(self, wallet_service, mock_db, sample_wallet):
        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_wallet
        
        wallet = await wallet_service.get_wallet(sample_wallet.id, sample_wallet.user_id)
        assert wallet == sample_wallet
    
    @pytest.mark.asyncio
    async def test_get_wallet_not_found(self, wallet_service, mock_db):
        mock_db.execute.return_value.scalar_one_or_none.return_value = None
        
        with pytest.raises(WalletNotFoundError):
            await wallet_service.get_wallet(uuid4())
    
    @pytest.mark.asyncio
    async def test_get_balance_success(self, wallet_service, mock_ledger, sample_wallet):
        mock_ledger.get_balance.return_value = BalanceResult(
            posted=Decimal("-1000.00"),  # Negative for liability
            pending=Decimal("-1100.00"),
            available=Decimal("-900.00"),
            currency="USD",
            as_of=datetime.now(timezone.utc),
        )
        
        balance = await wallet_service.get_balance(sample_wallet.id)
        
        assert balance.wallet_id == sample_wallet.id
        assert balance.currency == "USD"
        assert balance.posted_balance == Decimal("1000.00")  # Positive for user
        assert balance.pending_balance == Decimal("1100.00")
        assert balance.available_balance == Decimal("900.00")
    
    @pytest.mark.asyncio
    async def test_deposit_success(
        self, wallet_service, mock_db, mock_ledger, sample_wallet, sample_settlement_account, sample_liability_account
    ):
        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_wallet
        mock_ledger.get_account_by_code.side_effect = [sample_settlement_account, sample_liability_account]
        mock_ledger.create_transaction = AsyncMock(return_value=LedgerTransaction(
            id=uuid4(),
            reference="DEP-123",
            description="Deposit",
            status="POSTED",
            posted_at=datetime.now(timezone.utc),
        ))
        
        # Mock get_balance for return value
        mock_ledger.get_balance = AsyncMock(return_value=BalanceResult(
            posted=Decimal("-1100.00"),
            pending=Decimal("-1100.00"),
            available=Decimal("-1000.00"),
            currency="USD",
            as_of=datetime.now(timezone.utc),
        ))
        
        result = await wallet_service.deposit(
            wallet_id=sample_wallet.id,
            amount=Decimal("100.00"),
            description="Test deposit",
            idempotency_key="test-key-123",
        )
        
        assert result.amount == Decimal("100.00")
        assert result.currency == "USD"
        assert result.status == TransactionStatus.COMPLETED
        mock_ledger.create_transaction.assert_called_once()
        mock_db.add.assert_called()
        mock_db.commit.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_deposit_wallet_not_found(self, wallet_service, mock_db):
        mock_db.execute.return_value.scalar_one_or_none.return_value = None
        
        with pytest.raises(WalletNotFoundError):
            await wallet_service.deposit(
                wallet_id=uuid4(),
                amount=Decimal("100.00"),
                description="Test",
                idempotency_key="test",
            )
    
    @pytest.mark.asyncio
    async def test_deposit_wallet_frozen(self, wallet_service, mock_db, sample_wallet):
        sample_wallet.status = WalletStatus.FROZEN
        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_wallet
        
        with pytest.raises(WalletFrozenError):
            await wallet_service.deposit(
                wallet_id=sample_wallet.id,
                amount=Decimal("100.00"),
                description="Test",
                idempotency_key="test",
            )
    
    @pytest.mark.asyncio
    async def test_withdraw_success(
        self, wallet_service, mock_db, mock_ledger, sample_wallet, sample_settlement_account, sample_liability_account
    ):
        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_wallet
        mock_ledger.get_account_by_code.side_effect = [sample_liability_account, sample_settlement_account]
        mock_ledger.create_transaction = AsyncMock(return_value=LedgerTransaction(id=uuid4()))
        mock_ledger.get_balance = AsyncMock(return_value=BalanceResult(
            posted=Decimal("-900.00"),
            pending=Decimal("-900.00"),
            available=Decimal("-800.00"),
            currency="USD",
            as_of=datetime.now(timezone.utc),
        ))
        
        # Mock get_balance for validation
        wallet_service.get_balance = AsyncMock(return_value=WalletBalance(
            wallet_id=sample_wallet.id,
            currency="USD",
            posted_balance=Decimal("1000.00"),
            pending_balance=Decimal("1000.00"),
            available_balance=Decimal("1000.00"),
            as_of=datetime.now(timezone.utc),
        ))
        
        result = await wallet_service.withdraw(
            wallet_id=sample_wallet.id,
            amount=Decimal("100.00"),
            description="Test withdrawal",
            idempotency_key="test-key",
        )
        
        assert result.amount == Decimal("100.00")
        assert result.status == TransactionStatus.COMPLETED
    
    @pytest.mark.asyncio
    async def test_withdraw_insufficient_funds(self, wallet_service, sample_wallet):
        wallet_service.get_balance = AsyncMock(return_value=WalletBalance(
            wallet_id=sample_wallet.id,
            currency="USD",
            posted_balance=Decimal("50.00"),
            pending_balance=Decimal("50.00"),
            available_balance=Decimal("50.00"),
            as_of=datetime.now(timezone.utc),
        ))
        
        with pytest.raises(InsufficientFundsError, match="Available balance"):
            await wallet_service.withdraw(
                wallet_id=sample_wallet.id,
                amount=Decimal("100.00"),
                description="Test",
                idempotency_key="test",
            )
    
    @pytest.mark.asyncio
    async def test_transfer_success(
        self, wallet_service, mock_db, mock_ledger, mock_fraud, sample_wallet, sample_liability_account
    ):
        # Create destination wallet
        dest_wallet = Wallet(
            id=uuid4(),
            user_id=uuid4(),
            currency="USD",
            name="Dest Wallet",
            status=WalletStatus.ACTIVE,
        )
        
        # Mock wallet locks (both wallets)
        mock_db.execute.return_value.scalar_one_or_none.side_effect = [sample_wallet, dest_wallet]
        mock_ledger.get_account_by_code.return_value = sample_liability_account
        mock_ledger.create_transaction = AsyncMock(return_value=LedgerTransaction(id=uuid4()))
        
        # Mock fraud assessment
        mock_fraud.evaluate_transaction = AsyncMock(return_value=FraudAssessment(
            risk_score=Decimal("0.150"),
            risk_level="LOW",
            triggered_rules=[],
            all_rules=[],
        ))
        
        # Mock get_balance for source wallet
        wallet_service.get_balance = AsyncMock(return_value=WalletBalance(
            wallet_id=sample_wallet.id,
            currency="USD",
            posted_balance=Decimal("1000.00"),
            pending_balance=Decimal("1000.00"),
            available_balance=Decimal("1000.00"),
            as_of=datetime.now(timezone.utc),
        ))
        
        # Mock get_balance for destination (after transfer)
        mock_ledger.get_balance = AsyncMock(return_value=BalanceResult(
            posted=Decimal("-950.00"),
            pending=Decimal("-950.00"),
            available=Decimal("-950.00"),
            currency="USD",
            as_of=datetime.now(timezone.utc),
        ))
        
        source_result, dest_result = await wallet_service.transfer(
            source_wallet_id=sample_wallet.id,
            destination_wallet_id=dest_wallet.id,
            amount=Decimal("50.00"),
            description="Test transfer",
            idempotency_key="test-key",
        )
        
        assert source_result.amount == Decimal("50.00")
        assert source_result.status == TransactionStatus.COMPLETED
        assert dest_result.amount == Decimal("50.00")
        assert dest_result.status == TransactionStatus.COMPLETED
        mock_fraud.evaluate_transaction.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_transfer_same_wallet(self, wallet_service, sample_wallet):
        with pytest.raises(SameWalletTransferError):
            await wallet_service.transfer(
                source_wallet_id=sample_wallet.id,
                destination_wallet_id=sample_wallet.id,
                amount=Decimal("50.00"),
                description="Test",
                idempotency_key="test",
            )
    
    @pytest.mark.asyncio
    async def test_transfer_currency_mismatch(self, wallet_service, sample_wallet):
        dest_wallet = Wallet(
            id=uuid4(),
            user_id=uuid4(),
            currency="EUR",
            name="EUR Wallet",
            status=WalletStatus.ACTIVE,
        )
        
        with pytest.raises(CurrencyMismatchError):
            await wallet_service.transfer(
                source_wallet_id=sample_wallet.id,
                destination_wallet_id=dest_wallet.id,
                amount=Decimal("50.00"),
                description="Test",
                idempotency_key="test",
            )
    
    @pytest.mark.asyncio
    async def test_transfer_insufficient_funds(self, wallet_service, sample_wallet):
        dest_wallet = Wallet(
            id=uuid4(),
            user_id=uuid4(),
            currency="USD",
            name="Dest Wallet",
            status=WalletStatus.ACTIVE,
        )
        
        wallet_service.get_balance = AsyncMock(return_value=WalletBalance(
            wallet_id=sample_wallet.id,
            currency="USD",
            posted_balance=Decimal("10.00"),
            pending_balance=Decimal("10.00"),
            available_balance=Decimal("10.00"),
            as_of=datetime.now(timezone.utc),
        ))
        
        with pytest.raises(InsufficientFundsError):
            await wallet_service.transfer(
                source_wallet_id=sample_wallet.id,
                destination_wallet_id=dest_wallet.id,
                amount=Decimal("50.00"),
                description="Test",
                idempotency_key="test",
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])