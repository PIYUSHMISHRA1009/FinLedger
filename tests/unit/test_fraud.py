"""
FinLedger Unit Tests - Fraud Service
"""

import pytest
from decimal import Decimal
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta

from finledger.core.fraud.service import FraudService, FraudAssessment, RuleResult, RiskLevelThresholds
from finledger.core.fraud.exceptions import FraudError
from finledger.db.models import (
    FraudRule,
    FraudEvent,
    Transaction,
    Wallet,
    FraudRuleType,
    FraudRiskLevel,
    FraudEventStatus,
)
from sqlalchemy.ext.asyncio import AsyncSession


class TestFraudService:
    """Tests for FraudService."""
    
    @pytest.fixture
    def mock_db(self):
        return AsyncMock()
    
    @pytest.fixture
    def mock_redis(self):
        return AsyncMock()
    
    @pytest.fixture
    def fraud_service(self, mock_db, mock_redis):
        return FraudService(mock_db, mock_redis)
    
    @pytest.fixture
    def sample_user_id(self):
        return uuid4()
    
    @pytest.fixture
    def sample_wallet_id(self):
        return uuid4()
    
    @pytest.fixture
    def sample_transaction_id(self):
        return uuid4()
    
    @pytest.fixture
    def sample_rules(self):
        """Create sample fraud rules for testing."""
        return [
            FraudRule(
                id=uuid4(),
                code="VELOCITY_10PM",
                name="High Velocity - 10 Transactions/Minute",
                rule_type="VELOCITY",
                weight=Decimal("0.300"),
                parameters={"window_seconds": 60, "threshold": 10, "scope": "user"},
                active=True,
                priority=10,
            ),
            FraudRule(
                id=uuid4(),
                code="LARGE_TXN_ABS_10K",
                name="Large Transaction - Absolute > $10,000",
                rule_type="AMOUNT_THRESHOLD",
                weight=Decimal("0.400"),
                parameters={"threshold_amount": "10000"},
                active=True,
                priority=50,
            ),
            FraudRule(
                id=uuid4(),
                code="FREQUENT_COUNTERPARTY",
                name="Frequent Counterparty - >5 Transfers/Day",
                rule_type="COUNTERPARTY_FREQUENCY",
                weight=Decimal("0.200"),
                parameters={"window_hours": 24, "threshold": 5},
                active=True,
                priority=60,
            ),
            FraudRule(
                id=uuid4(),
                code="ROUND_NUMBER",
                name="Suspicious Round Number Amount",
                rule_type="SUSPICIOUS_PATTERN",
                weight=Decimal("0.150"),
                parameters={"round_thresholds": [100, 500, 1000, 5000, 10000], "tolerance": 0.01},
                active=True,
                priority=70,
            ),
        ]
    
    @pytest.mark.asyncio
    async def test_get_active_rules_cached(self, fraud_service, mock_db, sample_rules):
        mock_db.execute.return_value.scalars.return_value.all.return_value = sample_rules
        
        # First call
        rules1 = await fraud_service._get_active_rules()
        assert len(rules1) == 4
        
        # Second call should use cache
        rules2 = await fraud_service._get_active_rules()
        assert rules2 == rules1
        assert mock_db.execute.call_count == 1
    
    @pytest.mark.asyncio
    async def test_evaluate_velocity_rule_triggered(self, fraud_service, mock_redis, sample_user_id, sample_wallet_id):
        mock_redis.zcount.return_value = 15  # Above threshold of 10
        
        rule = FraudRule(
            id=uuid4(),
            code="VELOCITY_10PM",
            rule_type="VELOCITY",
            weight=Decimal("0.300"),
            parameters={"window_seconds": 60, "threshold": 10, "scope": "user"},
        )
        
        triggered, evidence = await fraud_service._evaluate_velocity_rule(
            rule, sample_user_id, sample_wallet_id
        )
        
        assert triggered is True
        assert evidence["count"] == 15
        assert evidence["threshold"] == 10
        assert evidence["scope"] == "user"
    
    @pytest.mark.asyncio
    async def test_evaluate_velocity_rule_not_triggered(self, fraud_service, mock_redis, sample_user_id, sample_wallet_id):
        mock_redis.zcount.return_value = 5  # Below threshold
        
        rule = FraudRule(
            id=uuid4(),
            code="VELOCITY_10PM",
            rule_type="VELOCITY",
            weight=Decimal("0.300"),
            parameters={"window_seconds": 60, "threshold": 10, "scope": "user"},
        )
        
        triggered, evidence = await fraud_service._evaluate_velocity_rule(
            rule, sample_user_id, sample_wallet_id
        )
        
        assert triggered is False
        assert evidence["count"] == 5
    
    @pytest.mark.asyncio
    async def test_evaluate_velocity_rule_wallet_scope(self, fraud_service, mock_redis, sample_user_id, sample_wallet_id):
        mock_redis.zcount.return_value = 25
        
        rule = FraudRule(
            id=uuid4(),
            code="VELOCITY_WALLET_20PM",
            rule_type="VELOCITY",
            weight=Decimal("0.200"),
            parameters={"window_seconds": 60, "threshold": 20, "scope": "wallet"},
        )
        
        triggered, evidence = await fraud_service._evaluate_velocity_rule(
            rule, sample_user_id, sample_wallet_id
        )
        
        assert triggered is True
        assert evidence["scope"] == "wallet"
    
    @pytest.mark.asyncio
    async def test_evaluate_amount_rule_absolute_triggered(self, fraud_service, mock_db, sample_user_id):
        rule = FraudRule(
            id=uuid4(),
            code="LARGE_TXN_ABS_10K",
            rule_type="AMOUNT_THRESHOLD",
            weight=Decimal("0.400"),
            parameters={"threshold_amount": "10000"},
        )
        
        triggered, evidence = await fraud_service._evaluate_amount_rule(
            rule, sample_user_id, Decimal("15000.00"), "USD"
        )
        
        assert triggered is True
        assert evidence["amount"] == "15000.00"
        assert evidence["threshold"] == "10000"
    
    @pytest.mark.asyncio
    async def test_evaluate_amount_rule_absolute_not_triggered(self, fraud_service, mock_db, sample_user_id):
        rule = FraudRule(
            id=uuid4(),
            code="LARGE_TXN_ABS_10K",
            rule_type="AMOUNT_THRESHOLD",
            weight=Decimal("0.400"),
            parameters={"threshold_amount": "10000"},
        )
        
        triggered, evidence = await fraud_service._evaluate_amount_rule(
            rule, sample_user_id, Decimal("5000.00"), "USD"
        )
        
        assert triggered is False
        assert evidence["amount"] == "5000.00"
    
    @pytest.mark.asyncio
    async def test_evaluate_amount_rule_percentile(self, fraud_service, mock_db, sample_user_id):
        # Mock historical transactions
        mock_db.execute.return_value.scalars.return_value.all.return_value = [
            Decimal("1000"), Decimal("2000"), Decimal("3000"), Decimal("4000"), 
            Decimal("5000"), Decimal("6000"), Decimal("7000"), Decimal("8000"),
            Decimal("9000"), Decimal("10000"),
        ]
        
        rule = FraudRule(
            id=uuid4(),
            code="LARGE_TXN_P95",
            rule_type="AMOUNT_THRESHOLD",
            weight=Decimal("0.350"),
            parameters={"percentile": 95, "lookback_days": 90, "min_transactions": 5},
        )
        
        triggered, evidence = await fraud_service._evaluate_amount_rule(
            rule, sample_user_id, Decimal("15000.00"), "USD"
        )
        
        # 95th percentile of 10 values = index 9 = 10000
        assert triggered is True
        assert evidence["threshold_value"] == "10000"
        assert evidence["percentile"] == 95
    
    @pytest.mark.asyncio
    async def test_evaluate_counterparty_rule_triggered(self, fraud_service, mock_db, sample_wallet_id):
        mock_db.execute.return_value.scalar.return_value = 6  # Above threshold of 5
        
        rule = FraudRule(
            id=uuid4(),
            code="FREQUENT_COUNTERPARTY",
            rule_type="COUNTERPARTY_FREQUENCY",
            weight=Decimal("0.200"),
            parameters={"window_hours": 24, "threshold": 5},
        )
        
        dest_wallet_id = uuid4()
        triggered, evidence = await fraud_service._evaluate_counterparty_rule(
            rule, sample_wallet_id, dest_wallet_id
        )
        
        assert triggered is True
        assert evidence["counterparty_transfers"] == 6
        assert evidence["threshold"] == 5
    
    @pytest.mark.asyncio
    async def test_evaluate_pattern_rule_round_number(self, fraud_service):
        rule = FraudRule(
            id=uuid4(),
            code="ROUND_NUMBER",
            rule_type="SUSPICIOUS_PATTERN",
            weight=Decimal("0.150"),
            parameters={"round_thresholds": [100, 500, 1000, 5000, 10000], "tolerance": 0.01},
        )
        
        # Exactly 1000
        triggered, evidence = await fraud_service._evaluate_pattern_rule(rule, Decimal("1000.00"))
        assert triggered is True
        assert "round_number_1000" in evidence["triggered_patterns"]
        
        # Close to 1000 (within 1%)
        triggered, evidence = await fraud_service._evaluate_pattern_rule(rule, Decimal("995.00"))
        assert triggered is True
        assert "round_number_1000" in evidence["triggered_patterns"]
        
        # Not round
        triggered, evidence = await fraud_service._evaluate_pattern_rule(rule, Decimal("1234.56"))
        assert triggered is False
    
    @pytest.mark.asyncio
    async def test_evaluate_pattern_rule_just_under_limit(self, fraud_service):
        rule = FraudRule(
            id=uuid4(),
            code="JUST_UNDER_LIMIT",
            rule_type="SUSPICIOUS_PATTERN",
            weight=Decimal("0.250"),
            parameters={"thresholds": [9999, 4999, 2999, 999], "tolerance": 10},
        )
        
        # Just under 10000
        triggered, evidence = await fraud_service._evaluate_pattern_rule(rule, Decimal("9995.00"))
        assert triggered is True
        assert "just_under_9999" in evidence["triggered_patterns"]
        
        # Not near threshold
        triggered, evidence = await fraud_service._evaluate_pattern_rule(rule, Decimal("5000.00"))
        assert triggered is False
    
    def test_calculate_risk_low(self, fraud_service):
        rule_results = [
            RuleResult(
                rule_id=uuid4(),
                rule_code="VELOCITY_10PM",
                rule_name="Velocity",
                weight=Decimal("0.300"),
                triggered=False,
                evidence={},
            ),
            RuleResult(
                rule_id=uuid4(),
                rule_code="LARGE_TXN",
                rule_name="Large Transaction",
                weight=Decimal("0.350"),
                triggered=False,
                evidence={},
            ),
        ]
        
        assessment = fraud_service._calculate_risk(rule_results)
        
        assert assessment.risk_score == Decimal("0.000")
        assert assessment.risk_level == "LOW"
        assert len(assessment.triggered_rules) == 0
    
    def test_calculate_risk_medium(self, fraud_service):
        rule_results = [
            RuleResult(
                rule_id=uuid4(),
                rule_code="VELOCITY_10PM",
                rule_name="Velocity",
                weight=Decimal("0.300"),
                triggered=True,
                evidence={},
            ),
            RuleResult(
                rule_id=uuid4(),
                rule_code="ROUND_NUMBER",
                rule_name="Round Number",
                weight=Decimal("0.150"),
                triggered=True,
                evidence={},
            ),
            RuleResult(
                rule_id=uuid4(),
                rule_code="LARGE_TXN",
                rule_name="Large Transaction",
                weight=Decimal("0.350"),
                triggered=False,
                evidence={},
            ),
        ]
        
        assessment = fraud_service._calculate_risk(rule_results)
        
        # (0.300 + 0.150) / (0.300 + 0.150 + 0.350) = 0.450 / 0.800 = 0.5625
        assert assessment.risk_score == Decimal("0.563")  # Rounded
        assert assessment.risk_level == "MEDIUM"
        assert len(assessment.triggered_rules) == 2
    
    def test_calculate_risk_high(self, fraud_service):
        rule_results = [
            RuleResult(
                rule_id=uuid4(),
                rule_code="VELOCITY_10PM",
                rule_name="Velocity",
                weight=Decimal("0.300"),
                triggered=True,
                evidence={},
            ),
            RuleResult(
                rule_id=uuid4(),
                rule_code="LARGE_TXN_ABS_10K",
                rule_name="Large Transaction",
                weight=Decimal("0.400"),
                triggered=True,
                evidence={},
            ),
            RuleResult(
                rule_id=uuid4(),
                rule_code="ROUND_NUMBER",
                rule_name="Round Number",
                weight=Decimal("0.150"),
                triggered=True,
                evidence={},
            ),
        ]
        
        assessment = fraud_service._calculate_risk(rule_results)
        
        # (0.300 + 0.400 + 0.150) / (0.300 + 0.400 + 0.150) = 1.0
        assert assessment.risk_score == Decimal("1.000")
        assert assessment.risk_level == "CRITICAL"
        assert len(assessment.triggered_rules) == 3
    
    def test_risk_level_thresholds(self):
        assert RiskLevelThresholds.LOW == Decimal("0.000")
        assert RiskLevelThresholds.MEDIUM == Decimal("0.300")
        assert RiskLevelThresholds.HIGH == Decimal("0.600")
        assert RiskLevelThresholds.CRITICAL == Decimal("0.850")


class TestFraudAssessment:
    """Tests for FraudAssessment dataclass."""
    
    def test_create_assessment(self):
        assessment = FraudAssessment(
            risk_score=Decimal("0.450"),
            risk_level="MEDIUM",
            triggered_rules=[],
            all_rules=[],
        )
        
        assert assessment.risk_score == Decimal("0.450")
        assert assessment.risk_level == "MEDIUM"
        assert assessment.event_id is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])