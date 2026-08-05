"""
FinLedger Advanced Fraud Rules (ML-ready)

Advanced fraud rule engine with:
- Rule chaining
- Shadow mode (dry-run)
- Dynamic thresholds
- Rule versioning
- A/B testing framework
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import List, Dict, Any, Optional, Callable, Set
from uuid import UUID, uuid4
from datetime import datetime, timezone
from enum import Enum
from abc import ABC, abstractmethod
from collections import defaultdict
import json
import hashlib

from sqlalchemy import select, func, and_, or_, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB

from finledger.db.models import FraudRule, FraudEvent, Transaction, Wallet, User
from finledger.core.fraud.service import FraudService, FraudAssessment, RuleResult, RiskLevelThresholds
from finledger.db.database import Base
from sqlalchemy import Column, String, DateTime, Boolean, Integer, ForeignKey, Text, Index
from sqlalchemy.dialects.postgresql import UUID as PG_UUID


# =============================================================================
# ENUMS & DATA CLASSES
# =============================================================================

class RuleChainOperator(str, Enum):
    """Operators for combining rule results in a chain."""
    AND = "AND"
    OR = "OR"
    WEIGHTED = "WEIGHTED"


class RuleExecutionMode(str, Enum):
    """Execution modes for rules."""
    LIVE = "LIVE"           # Normal production execution
    SHADOW = "SHADOW"       # Dry-run, no blocking, just logging
    AB_TEST = "AB_TEST"     # A/B testing (percentage of traffic)


class RuleVersionStatus(str, Enum):
    """Status of a rule version."""
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    DEPRECATED = "DEPRECATED"


@dataclass
class RuleCondition:
    """A single condition within a rule."""
    field: str                    # Field to check (e.g., "amount", "velocity_1m")
    operator: str                 # Comparison operator (>, <, ==, >=, <=, in, not_in)
    value: Any                    # Value to compare against
    weight: Decimal = Decimal("1.0")  # Weight for weighted scoring


@dataclass
class RuleChain:
    """A chain of rules with logical operators."""
    rules: List[UUID]                    # Rule IDs in execution order
    operator: RuleChainOperator = RuleChainOperator.WEIGHTED
    weights: Dict[UUID, Decimal] = field(default_factory=dict)  # Per-rule weights


@dataclass
class DynamicThreshold:
    """Dynamic threshold configuration."""
    rule_id: UUID
    metric: str                           # Metric to compute threshold for
    percentile: float = 95.0              # Percentile (e.g., 95 for P95)
    lookback_days: int = 30               # Historical window
    min_samples: int = 10                 # Minimum samples required
    update_frequency_hours: int = 24      # How often to recalculate
    manual_override: Optional[Decimal] = None  # Manual override value
    
    
@dataclass
class ABTestConfig:
    """A/B test configuration for a rule."""
    rule_id: UUID
    control_weight: Decimal = Decimal("1.0")    # Weight for control group
    treatment_weight: Decimal = Decimal("1.0")  # Weight for treatment group
    traffic_split: float = 0.5                   # 0.0-1.0, percentage to treatment
    start_date: datetime
    end_date: Optional[datetime] = None
    min_sample_size: int = 1000
    success_metric: str = "false_positive_rate"  # Metric to optimize


@dataclass
class RuleExecutionContext:
    """Context for rule evaluation."""
    transaction_id: UUID
    user_id: UUID
    wallet_id: UUID
    amount: Decimal
    currency: str
    metadata: Dict[str, Any]
    mode: RuleExecutionMode = RuleExecutionMode.LIVE
    ab_test_group: Optional[str] = None  # "control" or "treatment"


# =============================================================================
# DATABASE MODELS FOR ADVANCED FRAUD
# =============================================================================

class FraudRuleVersion(Base):
    """Versioned fraud rules with history."""
    __tablename__ = "fraud_rule_versions"
    
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    rule_id = Column(PG_UUID(as_uuid=True), ForeignKey("fraud_rules.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default=RuleVersionStatus.DRAFT)
    
    # Rule configuration snapshot
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    rule_type = Column(String(50), nullable=False)
    weight = Column(Numeric(4, 3), nullable=False)
    parameters = Column(JSONB, nullable=False, default=dict)
    priority = Column(Integer, nullable=False, default=100)
    
    # Advanced features
    execution_mode = Column(String(20), nullable=False, default=RuleExecutionMode.LIVE)
    dynamic_threshold = Column(JSONB, nullable=True)  # DynamicThreshold config
    ab_test_config = Column(JSONB, nullable=True)     # ABTestConfig
    chain_config = Column(JSONB, nullable=True)       # RuleChain config
    
    # Metadata
    created_by = Column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.now(timezone.utc))
    activated_at = Column(DateTime(timezone=True), nullable=True)
    archived_at = Column(DateTime(timezone=True), nullable=True)
    
    __table_args__ = (
        UniqueConstraint("rule_id", "version", name="uq_rule_version"),
        Index("idx_rule_version_status", "rule_id", "status"),
    )


class FraudRuleChain(Base):
    """Rule chains for complex logic."""
    __tablename__ = "fraud_rule_chains"
    
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    operator = Column(String(20), nullable=False, default=RuleChainOperator.WEIGHTED)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))


class FraudRuleChainRule(Base):
    """Rules within a chain."""
    __tablename__ = "fraud_rule_chain_rules"
    
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    chain_id = Column(PG_UUID(as_uuid=True), ForeignKey("fraud_rule_chains.id", ondelete="CASCADE"), nullable=False)
    rule_id = Column(PG_UUID(as_uuid=True), ForeignKey("fraud_rules.id", ondelete="CASCADE"), nullable=False)
    sequence = Column(Integer, nullable=False)
    weight = Column(Numeric(4, 3), default=Decimal("1.0"))
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.now(timezone.utc))
    
    __table_args__ = (
        UniqueConstraint("chain_id", "rule_id", name="uq_chain_rule"),
        Index("idx_chain_rule_sequence", "chain_id", "sequence"),
    )


class DynamicThresholdHistory(Base):
    """History of dynamic threshold calculations."""
    __tablename__ = "dynamic_threshold_history"
    
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    rule_id = Column(PG_UUID(as_uuid=True), ForeignKey("fraud_rules.id", ondelete="CASCADE"), nullable=False, index=True)
    metric = Column(String(100), nullable=False)
    percentile = Column(Numeric(5, 2), nullable=False)
    computed_value = Column(Numeric(19, 4), nullable=False)
    sample_count = Column(Integer, nullable=False)
    lookback_days = Column(Integer, nullable=False)
    computed_at = Column(DateTime(timezone=True), nullable=False, default=datetime.now(timezone.utc))
    is_active = Column(Boolean, default=True)
    
    __table_args__ = (
        Index("idx_threshold_history_rule_active", "rule_id", "is_active"),
    )


class ABTestResult(Base):
    """A/B test results tracking."""
    __tablename__ = "ab_test_results"
    
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    test_id = Column(PG_UUID(as_uuid=True), ForeignKey("fraud_ab_tests.id", ondelete="CASCADE"), nullable=False, index=True)
    group = Column(String(20), nullable=False)  # "control" or "treatment"
    transaction_count = Column(Integer, default=0)
    triggered_count = Column(Integer, default=0)
    blocked_count = Column(Integer, default=0)
    false_positive_count = Column(Integer, default=0)
    false_negative_count = Column(Integer, default=0)
    metric_value = Column(Numeric(10, 6), nullable=True)  # Computed success metric
    recorded_at = Column(DateTime(timezone=True), nullable=False, default=datetime.now(timezone.utc))
    window_start = Column(DateTime(timezone=True), nullable=False)
    window_end = Column(DateTime(timezone=True), nullable=False)


class FraudABTest(Base):
    """A/B test configuration for fraud rules."""
    __tablename__ = "fraud_ab_tests"
    
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    rule_id = Column(PG_UUID(as_uuid=True), ForeignKey("fraud_rules.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    
    # Traffic split
    traffic_split = Column(Numeric(3, 2), default=Decimal("0.50"))  # 0.0-1.0
    control_weight = Column(Numeric(4, 3), default=Decimal("1.0"))
    treatment_weight = Column(Numeric(4, 3), default=Decimal("1.0"))
    
    # Success metric
    success_metric = Column(String(50), default="false_positive_rate")
    min_sample_size = Column(Integer, default=1000)
    
    # Status
    status = Column(String(20), default="DRAFT")  # DRAFT, RUNNING, COMPLETED, STOPPED
    start_date = Column(DateTime(timezone=True), nullable=True)
    end_date = Column(DateTime(timezone=True), nullable=True)
    winner = Column(String(20), nullable=True)  # "control", "treatment", "inconclusive"
    
    created_by = Column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.now(timezone.utc))
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)


# =============================================================================
# ADVANCED FRAUD RULE ENGINE
# =============================================================================

class AdvancedFraudEngine:
    """
    Advanced fraud detection engine with:
    - Rule chaining
    - Shadow mode
    - Dynamic thresholds
    - Rule versioning
    - A/B testing
    """
    
    def __init__(self, db: AsyncSession, redis_client=None):
        self.db = db
        self.redis = redis_client
        self._threshold_cache: Dict[str, Decimal] = {}
        self._ab_test_assignments: Dict[str, str] = {}
    
    # -------------------------------------------------------------------------
    # RULE VERSIONING
    # -------------------------------------------------------------------------
    
    async def create_rule_version(
        self,
        rule_id: UUID,
        name: str,
        description: str,
        rule_type: str,
        weight: Decimal,
        parameters: Dict[str, Any],
        created_by: UUID,
        execution_mode: RuleExecutionMode = RuleExecutionMode.LIVE,
        dynamic_threshold: Optional[DynamicThreshold] = None,
        ab_test_config: Optional[ABTestConfig] = None,
        chain_config: Optional[RuleChain] = None,
    ) -> FraudRuleVersion:
        """Create a new version of a fraud rule."""
        # Get current max version
        result = await self.db.execute(
            select(func.max(FraudRuleVersion.version))
            .where(FraudRuleVersion.rule_id == rule_id)
        )
        max_version = result.scalar() or 0
        
        # Archive current active version
        await self.db.execute(
            update(FraudRuleVersion)
            .where(
                FraudRuleVersion.rule_id == rule_id,
                FraudRuleVersion.status == RuleVersionStatus.ACTIVE
            )
            .values(status=RuleVersionStatus.ARCHIVED, archived_at=datetime.now(timezone.utc))
        )
        
        # Create new version
        new_version = FraudRuleVersion(
            rule_id=rule_id,
            version=max_version + 1,
            status=RuleVersionStatus.DRAFT,
            name=name,
            description=description,
            rule_type=rule_type,
            weight=weight,
            parameters=parameters,
            execution_mode=execution_mode.value,
            dynamic_threshold=dynamic_threshold.__dict__ if dynamic_threshold else None,
            ab_test_config=ab_test_config.__dict__ if ab_test_config else None,
            chain_config=chain_config.__dict__ if chain_config else None,
            created_by=created_by,
        )
        
        self.db.add(new_version)
        await self.db.flush()
        return new_version
    
    async def activate_rule_version(self, version_id: UUID) -> FraudRuleVersion:
        """Activate a rule version."""
        result = await self.db.execute(
            select(FraudRuleVersion).where(FraudRuleVersion.id == version_id)
        )
        version = result.scalar_one_or_none()
        
        if not version:
            raise ValueError("Version not found")
        
        # Archive other active versions of same rule
        await self.db.execute(
            update(FraudRuleVersion)
            .where(
                FraudRuleVersion.rule_id == version.rule_id,
                FraudRuleVersion.status == RuleVersionStatus.ACTIVE
            )
            .values(status=RuleVersionStatus.ARCHIVED, archived_at=datetime.now(timezone.utc))
        )
        
        # Activate this version
        version.status = RuleVersionStatus.ACTIVE
        version.activated_at = datetime.now(timezone.utc)
        
        # Also update the base fraud_rule record
        await self.db.execute(
            update(FraudRule)
            .where(FraudRule.id == version.rule_id)
            .values(
                name=version.name,
                description=version.description,
                rule_type=version.rule_type,
                weight=version.weight,
                parameters=version.parameters,
                priority=version.priority,
            )
        )
        
        await self.db.commit()
        await self.db.refresh(version)
        return version
    
    # -------------------------------------------------------------------------
    # DYNAMIC THRESHOLDS
    # -------------------------------------------------------------------------
    
    async def compute_dynamic_threshold(self, config: DynamicThreshold) -> Decimal:
        """Compute dynamic threshold based on historical data."""
        # Query historical transactions
        cutoff = datetime.now(timezone.utc) - timedelta(days=config.lookback_days)
        
        # Get the metric values from completed transactions
        if config.metric == "amount":
            result = await self.db.execute(
                select(Transaction.amount)
                .where(
                    Transaction.created_at >= cutoff,
                    Transaction.status == TransactionStatus.COMPLETED,
                )
            )
            values = [row[0] for row in result.fetchall()]
        elif config.metric == "velocity":
            # Would need velocity tracking data
            values = []
        else:
            values = []
        
        if len(values) < config.min_samples:
            # Not enough samples, return manual override or 0
            return config.manual_override or Decimal("0")
        
        # Calculate percentile
        sorted_values = sorted(values)
        index = int(len(sorted_values) * config.percentile / 100)
        index = min(index, len(sorted_values) - 1)
        threshold = sorted_values[index]
        
        # Store in history
        history = DynamicThresholdHistory(
            rule_id=config.rule_id,
            metric=config.metric,
            percentile=Decimal(str(config.percentile)),
            computed_value=threshold,
            sample_count=len(values),
            lookback_days=config.lookback_days,
        )
        self.db.add(history)
        
        # Cache
        cache_key = f"threshold:{config.rule_id}:{config.metric}"
        self._threshold_cache[cache_key] = threshold
        
        return threshold
    
    async def get_dynamic_threshold(self, rule_id: UUID, metric: str) -> Optional[Decimal]:
        """Get current dynamic threshold from cache or compute."""
        cache_key = f"threshold:{rule_id}:{metric}"
        
        if cache_key in self._threshold_cache:
            return self._threshold_cache[cache_key]
        
        # Get latest from history
        result = await self.db.execute(
            select(DynamicThresholdHistory)
            .where(
                DynamicThresholdHistory.rule_id == rule_id,
                DynamicThresholdHistory.metric == metric,
                DynamicThresholdHistory.is_active == True
            )
            .order_by(desc(DynamicThresholdHistory.computed_at))
            .limit(1)
        )
        history = result.scalar_one_or_none()
        
        if history:
            self._threshold_cache[cache_key] = history.computed_value
            return history.computed_value
        
        return None
    
    # -------------------------------------------------------------------------
    # RULE CHAINS
    # -------------------------------------------------------------------------
    
    async def create_rule_chain(
        self,
        name: str,
        description: str,
        operator: RuleChainOperator,
        rules: List[UUID],
        weights: Optional[Dict[UUID, Decimal]] = None,
    ) -> FraudRuleChain:
        """Create a new rule chain."""
        chain = FraudRuleChain(
            name=name,
            description=description,
            operator=operator.value,
        )
        self.db.add(chain)
        await self.db.flush()
        
        # Add rules to chain
        for i, rule_id in enumerate(rules):
            weight = Decimal("1.0")
            if weights and rule_id in weights:
                weight = weights[rule_id]
            
            chain_rule = FraudRuleChainRule(
                chain_id=chain.id,
                rule_id=rule_id,
                sequence=i,
                weight=weight,
            )
            self.db.add(chain_rule)
        
        await self.db.commit()
        await self.db.refresh(chain)
        return chain
    
    async def evaluate_chain(
        self,
        chain: FraudRuleChain,
        context: RuleExecutionContext,
    ) -> FraudAssessment:
        """Evaluate a rule chain."""
        # Get chain rules
        result = await self.db.execute(
            select(FraudRuleChainRule)
            .where(FraudRuleChainRule.chain_id == chain.id)
            .order_by(FraudRuleChainRule.sequence)
        )
        chain_rules = result.scalars().all()
        
        rule_results = []
        total_weight = Decimal("0")
        triggered_weight = Decimal("0")
        
        for chain_rule in chain_rules:
            # Get rule version
            result = await self.db.execute(
                select(FraudRuleVersion)
                .where(
                    FraudRuleVersion.rule_id == chain_rule.rule_id,
                    FraudRuleVersion.status == RuleVersionStatus.ACTIVE
                )
                .order_by(desc(FraudRuleVersion.version))
                .limit(1)
            )
            version = result.scalar_one_or_none()
            
            if not version:
                continue
            
            # Evaluate rule
            triggered, evidence = await self._evaluate_single_rule(version, context)
            
            weight = chain_rule.weight
            total_weight += weight
            
            if triggered:
                triggered_weight += weight
            
            rule_results.append(RuleResult(
                rule_id=version.id,
                rule_code=version.parameters.get("code", "UNKNOWN"),
                rule_name=version.name,
                weight=weight,
                triggered=triggered,
                evidence=evidence,
            ))
        
        # Calculate final score
        if chain.operator == RuleChainOperator.AND:
            risk_score = Decimal("1.0") if all(r.triggered for r in rule_results) else Decimal("0.0")
        elif chain.operator == RuleChainOperator.OR:
            risk_score = Decimal("1.0") if any(r.triggered for r in rule_results) else Decimal("0.0")
        else:  # WEIGHTED
            risk_score = triggered_weight / total_weight if total_weight > 0 else Decimal("0")
        
        risk_score = min(Decimal("1.0"), max(Decimal("0.0"), risk_score))
        
        # Determine level
        if risk_score >= RiskLevelThresholds.CRITICAL:
            risk_level = FraudRiskLevel.CRITICAL
        elif risk_score >= RiskLevelThresholds.HIGH:
            risk_level = FraudRiskLevel.HIGH
        elif risk_score >= RiskLevelThresholds.MEDIUM:
            risk_level = FraudRiskLevel.MEDIUM
        else:
            risk_level = FraudRiskLevel.LOW
        
        return FraudAssessment(
            risk_score=risk_score.quantize(Decimal("0.001")),
            risk_level=risk_level,
            triggered_rules=[r for r in rule_results if r.triggered],
            all_rules=rule_results,
        )
    
    # -------------------------------------------------------------------------
    # SHADOW MODE & A/B TESTING
    # -------------------------------------------------------------------------
    
    def _get_ab_test_group(self, test_id: UUID, transaction_id: UUID) -> str:
        """Determine A/B test group assignment (consistent per transaction)."""
        # Consistent hashing for consistent assignment
        key = f"{test_id}:{transaction_id}"
        hash_val = int(hashlib.md5(key.encode()).hexdigest(), 16)
        
        # Get test config
        result = self.db.execute(
            select(FraudABTest).where(FraudABTest.id == test_id)
        )
        test = result.scalar_one_or_none()
        
        if not test or test.status != "RUNNING":
            return "control"
        
        if hash_val % 10000 / 10000 < float(test.traffic_split):
            return "treatment"
        return "control"
    
    async def evaluate_with_advanced_features(
        self,
        context: RuleExecutionContext,
    ) -> FraudAssessment:
        """
        Main evaluation entry point with all advanced features.
        """
        # Check for active A/B test
        test_result = await self.db.execute(
            select(FraudABTest)
            .where(
                FraudABTest.status == "RUNNING",
                FraudABTest.start_date <= datetime.now(timezone.utc),
                or_(FraudABTest.end_date.is_(None), FraudABTest.end_date >= datetime.now(timezone.utc)),
            )
        )
        active_tests = list(test_result.scalars().all())
        
        # Determine test group for this transaction
        ab_test_group = "control"
        for test in active_tests:
            if self._get_ab_test_group(test.id, context.transaction_id) == "treatment":
                ab_test_group = "treatment"
                break
        
        context.ab_test_group = ab_test_group
        
        # Get active rules and chains
        result = await self.db.execute(
            select(FraudRuleVersion)
            .where(FraudRuleVersion.status == RuleVersionStatus.ACTIVE)
            .order_by(FraudRuleVersion.priority)
        )
        active_versions = result.scalars().all()
        
        # Evaluate individual rules
        rule_results = []
        for version in active_versions:
            # Check execution mode
            mode = RuleExecutionMode(version.execution_mode)
            
            # For shadow mode, evaluate but don't block
            if mode == RuleExecutionMode.SHADOW and context.mode != RuleExecutionMode.SHADOW:
                # Still evaluate for logging but don't affect decision
                pass
            
            # Check A/B test group weight
            weight = version.weight
            if context.ab_test_group == "treatment" and version.ab_test_config:
                weight = Decimal(str(version.ab_test_config.get("treatment_weight", "1.0")))
            elif context.ab_test_group == "control" and version.ab_test_config:
                weight = Decimal(str(version.ab_test_config.get("control_weight", "1.0")))
            
            # Evaluate rule
            triggered, evidence = await self._evaluate_single_rule(version, context)
            
            rule_results.append(RuleResult(
                rule_id=version.id,
                rule_code=version.parameters.get("code", "UNKNOWN"),
                rule_name=version.name,
                weight=weight,
                triggered=triggered,
                evidence=evidence,
            ))
        
        # Check for rule chains
        chain_result = await self.db.execute(
            select(FraudRuleChain).where(FraudRuleChain.is_active == True)
        )
        chains = result.scalars().all()
        
        for chain in chains:
            chain_assessment = await self.evaluate_chain(chain, context)
            # Merge chain results
            rule_results.extend(chain_assessment.all_rules)
        
        # Calculate final assessment
        return self._calculate_final_assessment(rule_results, context)
    
    async def _evaluate_single_rule(
        self,
        version: FraudRuleVersion,
        context: RuleExecutionContext,
    ) -> tuple[bool, Dict[str, Any]]:
        """Evaluate a single rule version."""
        rule_type = version.rule_type
        params = version.parameters
        
        if rule_type == "VELOCITY":
            return await self._evaluate_velocity(version, context)
        elif rule_type == "AMOUNT_THRESHOLD":
            return await self._evaluate_amount(version, context)
        elif rule_type == "COUNTERPARTY_FREQUENCY":
            return await self._evaluate_counterparty(version, context)
        elif rule_type == "SUSPICIOUS_PATTERN":
            return await self._evaluate_pattern(version, context)
        elif rule_type == "GEO_VELOCITY":
            return await self._evaluate_geo(version, context)
        elif rule_type == "ML_SCORE":
            return await self._evaluate_ml(version, context)
        
        return False, {"reason": "Unknown rule type"}
    
    async def _evaluate_velocity(
        self,
        version: FraudRuleVersion,
        context: RuleExecutionContext,
    ) -> tuple[bool, Dict[str, Any]]:
        """Evaluate velocity rule with dynamic threshold support."""
        params = version.parameters
        scope = params.get("scope", "user")
        window = params.get("window_seconds", 60)
        
        if scope == "user":
            entity_id = context.user_id
        elif scope == "wallet":
            entity_id = context.wallet_id
        else:
            entity_id = context.user_id
        
        count = await self._get_velocity_count(entity_id, scope, window)
        
        # Check dynamic threshold
        threshold = params.get("threshold", 10)
        dynamic_config = version.dynamic_threshold
        if dynamic_config and dynamic_config.get("metric") == "velocity":
            dynamic_threshold = await self.get_dynamic_threshold(version.id, "velocity")
            if dynamic_threshold:
                threshold = dynamic_threshold
        
        triggered = count > threshold
        evidence = {
            "count": count,
            "threshold": threshold,
            "window_seconds": window,
            "scope": scope,
        }
        
        return triggered, evidence
    
    async def _evaluate_amount(
        self,
        version: FraudRuleVersion,
        context: RuleExecutionContext,
    ) -> tuple[bool, Dict[str, Any]]:
        """Evaluate amount threshold rule."""
        params = version.parameters
        threshold_type = params.get("threshold_type", "absolute")
        
        if threshold_type == "absolute":
            threshold = Decimal(str(params.get("threshold_amount", 10000)))
            triggered = context.amount >= threshold
            evidence = {"amount": str(context.amount), "threshold": str(threshold)}
        
        elif threshold_type == "percentile":
            # Use dynamic threshold
            dynamic_threshold = await self.get_dynamic_threshold(version.id, "amount")
            if dynamic_threshold:
                threshold = dynamic_threshold
            else:
                # Fallback to computed percentile
                percentile = params.get("percentile", 95)
                lookback = params.get("lookback_days", 90)
                min_txns = params.get("min_transactions", 10)
                
                cutoff = datetime.now(timezone.utc) - timedelta(days=lookback)
                result = await self.db.execute(
                    select(Transaction.amount)
                    .where(
                        Transaction.user_id == context.user_id,
                        Transaction.status == TransactionStatus.COMPLETED,
                        Transaction.created_at >= cutoff,
                    )
                    .order_by(Transaction.amount)
                )
                amounts = [row[0] for row in result.fetchall()]
                
                if len(amounts) < params.get("min_transactions", 10):
                    return False, {"reason": "Insufficient transaction history"}
                
                index = int(len(amounts) * percentile / 100)
                threshold = amounts[min(index, len(amounts) - 1)]
                triggered = context.amount >= threshold
                evidence = {
                    "amount": str(context.amount),
                    "percentile": percentile,
                    "threshold_value": str(threshold),
                }
        
        else:
            triggered = False
            evidence = {"error": "Unknown threshold type"}
        
        return triggered, evidence
    
    async def _evaluate_counterparty(
        self,
        version: FraudRuleVersion,
        context: RuleExecutionContext,
    ) -> tuple[bool, Dict[str, Any]]:
        """Evaluate counterparty frequency rule."""
        params = version.parameters
        window_hours = params.get("window_hours", 24)
        threshold = params.get("threshold", 5)
        
        if not context.metadata.get("destination_wallet_id"):
            return False, {"reason": "No destination wallet"}
        
        dest_wallet_id = UUID(context.metadata["destination_wallet_id"])
        cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
        
        result = await self.db.execute(
            select(func.count(Transaction.id))
            .where(
                Transaction.source_wallet_id == context.wallet_id,
                Transaction.destination_wallet_id == dest_wallet_id,
                Transaction.type == TransactionType.TRANSFER_OUT,
                Transaction.status == TransactionStatus.COMPLETED,
                Transaction.created_at >= cutoff,
            )
        )
        count = result.scalar() or 0
        
        triggered = count >= threshold
        evidence = {
            "counterparty_transfers": count,
            "threshold": threshold,
            "window_hours": window_hours,
        }
        
        return triggered, evidence
    
    async def _evaluate_pattern(
        self,
        version: FraudRuleVersion,
        context: RuleExecutionContext,
    ) -> tuple[bool, Dict[str, Any]]:
        """Evaluate suspicious pattern rule."""
        params = version.parameters
        triggered_patterns = []
        
        # Round number check
        if "round_thresholds" in params:
            thresholds = params["round_thresholds"]
            tolerance = params.get("tolerance", 0.01)
            
            for threshold in thresholds:
                diff = abs(context.amount - Decimal(str(threshold))) / Decimal(str(threshold))
                if diff <= Decimal(str(tolerance)):
                    triggered_patterns.append(f"round_number_{threshold}")
        
        # Just under limit check
        if "thresholds" in params:
            thresholds = params["thresholds"]
            tolerance = params.get("tolerance", 10)
            
            for threshold in thresholds:
                if Decimal(str(threshold - tolerance)) <= context.amount < Decimal(str(threshold)):
                    triggered_patterns.append(f"just_under_{threshold}")
        
        triggered = len(triggered_patterns) > 0
        evidence = {"triggered_patterns": triggered_patterns}
        
        return triggered, evidence
    
    async def _evaluate_geo(
        self,
        version: FraudRuleVersion,
        context: RuleExecutionContext,
    ) -> tuple[bool, Dict[str, Any]]:
        """Evaluate geo velocity rule."""
        # Placeholder - would need IP geolocation
        return False, {"reason": "Geo evaluation not implemented"}
    
    async def _evaluate_ml(
        self,
        version: FraudRuleVersion,
        context: RuleExecutionContext,
    ) -> tuple[bool, Dict[str, Any]]:
        """Evaluate ML score rule (placeholder for future ML integration)."""
        return False, {"reason": "ML scoring not implemented"}
    
    def _calculate_final_assessment(
        self,
        rule_results: List[RuleResult],
        context: RuleExecutionContext,
    ) -> FraudAssessment:
        """Calculate final risk assessment from all rule results."""
        triggered_weight = sum(r.weight for r in rule_results if r.triggered)
        total_weight = sum(r.weight for r in rule_results)
        
        if total_weight > 0:
            normalized_score = triggered_weight / total_weight
        else:
            normalized_score = Decimal("0.000")
        
        normalized_score = min(Decimal("1.0"), max(Decimal("0.0"), normalized_score))
        
        # Determine level
        if normalized_score >= RiskLevelThresholds.CRITICAL:
            risk_level = FraudRiskLevel.CRITICAL
        elif normalized_score >= RiskLevelThresholds.HIGH:
            risk_level = FraudRiskLevel.HIGH
        elif normalized_score >= RiskLevelThresholds.MEDIUM:
            risk_level = FraudRiskLevel.MEDIUM
        else:
            risk_level = FraudRiskLevel.LOW
        
        return FraudAssessment(
            risk_score=normalized_score.quantize(Decimal("0.001")),
            risk_level=risk_level,
            triggered_rules=[r for r in rule_results if r.triggered],
            all_rules=rule_results,
        )
    
    async def _get_velocity_count(
        self,
        entity_id: UUID,
        scope: str,
        window_seconds: int,
    ) -> int:
        """Get velocity count from Redis."""
        if not self.redis:
            return 0
        
        key = f"vel:{scope}:{entity_id}"
        now = datetime.now(timezone.utc).timestamp()
        window_start = now - window_seconds
        
        return await self.redis.zcount(key, window_start, now)


# =============================================================================
# ADMIN API FOR ADVANCED FRAUD FEATURES
# =============================================================================

advanced_fraud_router = APIRouter(prefix="/admin/fraud/advanced", tags=["Advanced Fraud"])


@advanced_fraud_router.post(
    "/rules/{rule_id}/versions",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
)
async def create_rule_version(
    rule_id: UUID,
    request: dict,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    """Create a new version of a fraud rule."""
    engine = AdvancedFraudEngine(db)
    
    version = await engine.create_rule_version(
        rule_id=rule_id,
        name=request["name"],
        description=request.get("description", ""),
        rule_type=request["rule_type"],
        weight=Decimal(str(request["weight"])),
        parameters=request["parameters"],
        created_by=current_user.id,
        execution_mode=RuleExecutionMode(request.get("execution_mode", "LIVE")),
        dynamic_threshold=DynamicThreshold(**request["dynamic_threshold"]) if request.get("dynamic_threshold") else None,
        ab_test_config=ABTestConfig(**request["ab_test_config"]) if request.get("ab_test_config") else None,
        chain_config=RuleChain(**request["chain_config"]) if request.get("chain_config") else None,
    )
    
    return {"id": str(version.id), "version": version.version, "status": version.status.value}


@advanced_fraud_router.post(
    "/versions/{version_id}/activate",
    response_model=dict,
)
async def activate_rule_version(
    version_id: UUID,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    """Activate a rule version."""
    engine = AdvancedFraudEngine(db)
    version = await engine.activate_rule_version(version_id)
    return {"id": str(version.id), "status": version.status.value, "activated_at": version.activated_at.isoformat()}


@advanced_fraud_router.post(
    "/chains",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
)
async def create_rule_chain(
    request: dict,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    """Create a new rule chain."""
    engine = AdvancedFraudEngine(db)
    
    chain = await engine.create_rule_chain(
        name=request["name"],
        description=request.get("description", ""),
        operator=RuleChainOperator(request["operator"]),
        rules=[UUID(r) for r in request["rules"]],
        weights={UUID(k): Decimal(str(v)) for k, v in request.get("weights", {}).items()},
    )
    
    return {"id": str(chain.id), "name": chain.name, "operator": chain.operator.value}


@advanced_fraud_router.post(
    "/ab-tests",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
)
async def create_ab_test(
    request: dict,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    """Create a new A/B test for a fraud rule."""
    test = FraudABTest(
        rule_id=UUID(request["rule_id"]),
        name=request["name"],
        description=request.get("description", ""),
        traffic_split=Decimal(str(request.get("traffic_split", "0.5"))),
        control_weight=Decimal(str(request.get("control_weight", "1.0"))),
        treatment_weight=Decimal(str(request.get("treatment_weight", "1.0"))),
        success_metric=request.get("success_metric", "false_positive_rate"),
        min_sample_size=request.get("min_sample_size", 1000),
        start_date=datetime.fromisoformat(request["start_date"]) if request.get("start_date") else None,
        end_date=datetime.fromisoformat(request["end_date"]) if request.get("end_date") else None,
        created_by=current_user.id,
    )
    
    db.add(test)
    await db.commit()
    await db.refresh(test)
    
    return {"id": str(test.id), "name": test.name, "status": test.status}


@advanced_fraud_router.post(
    "/ab-tests/{test_id}/start",
    response_model=dict,
)
async def start_ab_test(
    test_id: UUID,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    """Start an A/B test."""
    result = await db.execute(select(FraudABTest).where(FraudABTest.id == test_id))
    test = result.scalar_one_or_none()
    
    if not test:
        raise HTTPException(status_code=404, detail="A/B test not found")
    
    test.status = "RUNNING"
    test.started_at = datetime.now(timezone.utc)
    await db.commit()
    
    return {"id": str(test.id), "status": test.status, "started_at": test.started_at.isoformat()}


@advanced_fraud_router.get(
    "/ab-tests/{test_id}/results",
    response_model=dict,
)
async def get_ab_test_results(
    test_id: UUID,
    current_user: User = Depends(require_permission("fraud:read")),
    db: AsyncSession = Depends(get_db),
):
    """Get A/B test results."""
    result = await db.execute(
        select(ABTestResult)
        .where(ABTestResult.test_id == test_id)
        .order_by(ABTestResult.recorded_at.desc())
    )
    results = result.scalars().all()
    
    return {
        "test_id": str(test_id),
        "results": [
            {
                "group": r.group,
                "transaction_count": r.transaction_count,
                "triggered_count": r.triggered_count,
                "blocked_count": r.blocked_count,
                "metric_value": str(r.metric_value) if r.metric_value else None,
                "window_start": r.window_start.isoformat(),
                "window_end": r.window_end.isoformat(),
            }
            for r in results
        ],
    }