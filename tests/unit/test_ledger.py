"""
FinLedger Unit Tests - Ledger Service
"""

import pytest
from decimal import Decimal
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from finledger.core.ledger.service import LedgerService, LedgerEntrySpec, LedgerEntryType, BalanceResult
from finledger.core.ledger.exceptions import (
    LedgerValidationError,
    LedgerImbalanceError,
    AccountNotFoundError,
)
from finledger.db.models import (
    LedgerAccount,
    LedgerTransaction,
    LedgerEntry,
    AccountBalance,
    AccountType,
    AccountNormality,
    LedgerTxnStatus,
    LedgerEntryType as ModelLedgerEntryType,
)
from sqlalchemy.ext.asyncio import AsyncSession


class TestLedgerService:
    """Tests for LedgerService."""
    
    @pytest.fixture
    def mock_db(self):
        return AsyncMock(spec=AsyncSession)
    
    @pytest.fixture
    def ledger_service(self, mock_db):
        return LedgerService(mock_db)
    
    @pytest.fixture
    def sample_accounts(self):
        """Create sample ledger accounts for testing."""
        return {
            "1010": LedgerAccount(
                id=uuid4(),
                code="1010",
                name="Customer Wallets - USD",
                account_type=AccountType.ASSET,
                normality=AccountNormality.DEBIT,
                is_active=True,
                is_system_account=True,
            ),
            "2010": LedgerAccount(
                id=uuid4(),
                code="2010",
                name="Customer Liabilities - USD",
                account_type=AccountType.LIABILITY,
                normality=AccountNormality.CREDIT,
                is_active=True,
                is_system_account=True,
            ),
            "1030": LedgerAccount(
                id=uuid4(),
                code="1030",
                name="Settlement Accounts",
                account_type=AccountType.ASSET,
                normality=AccountNormality.DEBIT,
                is_active=True,
                is_system_account=True,
            ),
            "4010": LedgerAccount(
                id=uuid4(),
                code="4010",
                name="Transaction Fees",
                account_type=AccountType.REVENUE,
                normality=AccountNormality.CREDIT,
                is_active=True,
                is_system_account=True,
            ),
        }
    
    @pytest.mark.asyncio
    async def test_get_account_by_code(self, ledger_service, mock_db, sample_accounts):
        account = sample_accounts["1010"]
        mock_db.execute.return_value.scalar_one_or_none.return_value = account
        
        result = await ledger_service.get_account_by_code("1010")
        assert result == account
        assert result.code == "1010"
    
    @pytest.mark.asyncio
    async def test_get_account_by_code_not_found(self, ledger_service, mock_db):
        mock_db.execute.return_value.scalar_one_or_none.return_value = None
        
        with pytest.raises(AccountNotFoundError):
            await ledger_service.get_account_by_code("9999")
    
    def test_validate_balanced_success(self, ledger_service):
        entries = [
            LedgerEntrySpec("1010", LedgerEntryType.DEBIT, Decimal("100.00")),
            LedgerEntrySpec("2010", LedgerEntryType.CREDIT, Decimal("100.00")),
        ]
        # Should not raise
        ledger_service._validate_balanced(entries)
    
    def test_validate_balanced_fails_debits_neq_credits(self, ledger_service):
        entries = [
            LedgerEntrySpec("1010", LedgerEntryType.DEBIT, Decimal("100.00")),
            LedgerEntrySpec("2010", LedgerEntryType.CREDIT, Decimal("50.00")),
        ]
        with pytest.raises(LedgerImbalanceError):
            ledger_service._validate_balanced(entries)
    
    def test_validate_balanced_fails_too_few_entries(self, ledger_service):
        entries = [
            LedgerEntrySpec("1010", LedgerEntryType.DEBIT, Decimal("100.00")),
        ]
        with pytest.raises(LedgerValidationError):
            ledger_service._validate_balanced(entries)
    
    def test_calculate_balance_deltas_debit_normal_debit(self, ledger_service):
        """DEBIT-normal account (ASSET) with DEBIT entry increases balance."""
        account = LedgerAccount(
            normality=AccountNormality.DEBIT,
            account_type="ASSET",
        )
        posted, pending, available = ledger_service._calculate_balance_deltas(
            account, LedgerEntryType.DEBIT, Decimal("100.00")
        )
        assert posted == Decimal("100.00")
        assert pending == Decimal("100.00")
        assert available == Decimal("100.00")
    
    def test_calculate_balance_deltas_debit_normal_credit(self, ledger_service):
        """DEBIT-normal account (ASSET) with CREDIT entry decreases balance."""
        account = LedgerAccount(
            normality=AccountNormality.DEBIT,
            account_type="ASSET",
        )
        posted, pending, available = ledger_service._calculate_balance_deltas(
            account, LedgerEntryType.CREDIT, Decimal("100.00")
        )
        assert posted == Decimal("-100.00")
        assert pending == Decimal("-100.00")
        assert available == Decimal("0")  # Conservative: pending inflows not counted
    
    def test_calculate_balance_deltas_credit_normal_credit(self, ledger_service):
        """CREDIT-normal account (LIABILITY) with CREDIT entry increases balance."""
        account = LedgerAccount(
            normality=AccountNormality.CREDIT,
            account_type="LIABILITY",
        )
        posted, pending, available = ledger_service._calculate_balance_deltas(
            account, LedgerEntryType.CREDIT, Decimal("100.00")
        )
        assert posted == Decimal("100.00")
        assert pending == Decimal("100.00")
        assert available == Decimal("0")  # Conservative: pending inflows not counted
    
    def test_calculate_balance_deltas_credit_normal_debit(self, ledger_service):
        """CREDIT-normal account (LIABILITY) with DEBIT entry decreases balance."""
        account = LedgerAccount(
            normality=AccountNormality.CREDIT,
            account_type="LIABILITY",
        )
        posted, pending, available = ledger_service._calculate_balance_deltas(
            account, LedgerEntryType.DEBIT, Decimal("100.00")
        )
        assert posted == Decimal("-100.00")
        assert pending == Decimal("-100.00")
        assert available == Decimal("-100.00")  # Pending outflows reduce available


class TestLedgerEntrySpec:
    """Tests for LedgerEntrySpec dataclass."""
    
    def test_create_entry_spec(self):
        entry = LedgerEntrySpec(
            account_code="1010",
            entry_type=LedgerEntryType.DEBIT,
            amount=Decimal("100.00"),
            description="Test entry",
        )
        assert entry.account_code == "1010"
        assert entry.entry_type == LedgerEntryType.DEBIT
        assert entry.amount == Decimal("100.00")
        assert entry.description == "Test entry"
    
    def test_entry_spec_optional_fields(self):
        entry = LedgerEntrySpec(
            account_code="2010",
            entry_type=LedgerEntryType.CREDIT,
            amount=Decimal("50.00"),
        )
        assert entry.description is None
        assert entry.wallet_id is None
        assert entry.metadata is None


class TestBalanceResult:
    """Tests for BalanceResult dataclass."""
    
    def test_create_balance_result(self):
        now = datetime.now(timezone.utc)
        result = BalanceResult(
            posted=Decimal("100.00"),
            pending=Decimal("150.00"),
            available=Decimal("50.00"),
            currency="USD",
            as_of=now,
        )
        assert result.posted == Decimal("100.00")
        assert result.pending == Decimal("150.00")
        assert result.available == Decimal("50.00")
        assert result.currency == "USD"
        assert result.as_of == now


if __name__ == "__main__":
    pytest.main([__file__, "-v"])