"""
FinLedger Fraud Service

Rule-based fraud detection engine with velocity tracking and risk scoring.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import List, Dict, Any, Optional, Set
from uuid import UUID, uuid4
from datetime import datetime, timezone, timedelta
from enum import Enum
import json

from sqlalchemy import select, func, and_, or_, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from finledger.db.models import (
    FraudRule,
    FraudEvent,
    Transaction,
    FraudRuleType,
    FraudRiskLevel,
    FraudEventStatus,
    Wallet,
    User,
)
from finledger.core.exceptions import FraudError
from finledger.api.config.settings import get_settings


@dataclass
class RuleResult:
    """Result of a single rule evaluation."""
    rule_id: UUID
    rule_code: str
    rule_name: str
    weight: Decimal
    triggered: bool
    evidence: Dict[str, Any]


@dataclass
class FraudAssessment:
    """Complete fraud assessment result."""
    risk_score: Decimal  # 0.000 to 1.000
    risk_level: FraudRiskLevel
    triggered_rules: List[RuleResult]
    all_rules: List[RuleResult]
    event_id: Optional[UUID] = None


class RiskLevelThresholds:
    """Risk level thresholds."""
    LOW = Decimal("0.000")
    MEDIUM = Decimal("0.300")
    HIGH = Decimal("0.600")
    CRITICAL = Decimal("0.850")


class FraudService:
    """Fraud detection engine with rule-based scoring."""
    
    def __init__(self, db: AsyncSession, redis_client=None):
        self.db = db
        self.redis = redis_client
        self._rules_cache: List[FraudRule] = []
        self._cache_timestamp: float = 0
        self._cache_ttl = 60  # seconds
    
    async def _get_active_rules(self) -> List[FraudRule]:
        """Get active fraud rules with caching."""
        import time
        now = time.time()
        
        if now - self._cache_timestamp > self._cache_ttl or not self._rules_cache:
            result = await self.db.execute(
                select(FraudRule)
                .where(FraudRule.active == True)
                .order_by(FraudRule.priority)
            )
            self._rules_cache = result.scalars().all()
            self._cache_timestamp = now
        
        return self._rules_cache
    
    async def evaluate_transaction(
        self,
        transaction_id: UUID,
        source_wallet_id: UUID,
        destination_wallet_id: Optional[UUID],
        amount: Decimal,
        currency: str,
        user_id: Optional[UUID] = None,
        ip_address: Optional[str] = None,
        device_fingerprint: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ) -> FraudAssessment:
        """
        Evaluate a transaction for fraud risk.
        
        This is called asynchronously during transaction processing.
        """
        # Get user_id if not provided
        if not user_id and source_wallet_id:
            wallet_result = await self.db.execute(
                select(Wallet).where(Wallet.id == source_wallet_id)
            )
            wallet = wallet_result.scalar_one_or_none()
            if wallet:
                user_id = wallet.user_id
        
        if not user_id:
            # Can't evaluate without user context
            return FraudAssessment(
                risk_score=Decimal("0.000"),
                risk_level=FraudRiskLevel.LOW,
                triggered_rules=[],
                all_rules=[],
            )
        
        # Update velocity counters (async, non-blocking)
        if self.redis:
            await self._update_velocity_counters(user_id, source_wallet_id, transaction_id)
        
        # Get active rules
        rules = await self._get_active_rules()
        
        # Evaluate each rule
        rule_results = []
        for rule in rules:
            try:
                triggered, evidence = await self._evaluate_rule(
                    rule, user_id, source_wallet_id, destination_wallet_id,
                    amount, currency, transaction_id
                )
                rule_results.append(RuleResult(
                    rule_id=rule.id,
                    rule_code=rule.code,
                    rule_name=rule.name,
                    weight=rule.weight,
                    triggered=triggered,
                    evidence=evidence,
                ))
            except Exception as e:
                # Log error but continue evaluation
                import logging
                logging.error(f"Error evaluating rule {rule.code}: {e}")
                rule_results.append(RuleResult(
                    rule_id=rule.id,
                    rule_code=rule.code,
                    rule_name=rule.name,
                    weight=rule.weight,
                    triggered=False,
                    evidence={"error": str(e)},
                ))
        
        # Calculate risk score
        assessment = self._calculate_risk(rule_results)
        
        # Persist fraud event
        event_id = await self._persist_fraud_event(
            transaction_id=transaction_id,
            user_id=user_id,
            wallet_id=source_wallet_id,
            assessment=assessment,
        )
        assessment.event_id = event_id
        
        return assessment
    
    async def _update_velocity_counters(
        self,
        user_id: UUID,
        wallet_id: UUID,
        transaction_id: UUID,
    ) -> None:
        """Update velocity counters in Redis."""
        now = datetime.now(timezone.utc).timestamp()
        
        # Keys for different scopes
        keys = {
            f"vel:user:{user_id}": 3600,    # 1 hour
            f"vel:user:{user_id}:1m": 60,    # 1 minute
            f"vel:wallet:{wallet_id}": 3600, # 1 hour
            f"vel:wallet:{wallet_id}:1m": 60,# 1 minute
        }
        
        pipe = self.redis.pipeline()
        for key, window in keys.items():
            pipe.zadd(key, {str(transaction_id): now})
            pipe.expire(key, window + 60)
        
        await pipe.execute()
    
    async def _get_velocity_count(
        self,
        scope: str,
        entity_id: UUID,
        window_seconds: int,
    ) -> int:
        """Get velocity count for entity in time window."""
        if not self.redis:
            return 0
        
        key = f"vel:{scope}:{entity_id}"
        if window_seconds <= 60:
            key += ":1m"
        
        now = datetime.now(timezone.utc).timestamp()
        window_start = now - window_seconds
        
        return await self.redis.zcount(key, window_start, now)
    
    async def _evaluate_rule(
        self,
        rule: FraudRule,
        user_id: UUID,
        source_wallet_id: UUID,
        destination_wallet_id: Optional[UUID],
        amount: Decimal,
        currency: str,
        transaction_id: UUID,
    ) -> tuple[bool, Dict[str, Any]]:
        """Evaluate a single fraud rule."""
        
        if rule.rule_type == FraudRuleType.VELOCITY:
            return await self._evaluate_velocity_rule(rule, user_id, source_wallet_id)
        
        elif rule.rule_type == FraudRuleType.AMOUNT_THRESHOLD:
            return await self._evaluate_amount_rule(rule, user_id, amount, currency)
        
        elif rule.rule_type == FraudRuleType.COUNTERPARTY_FREQUENCY:
            return await self._evaluate_counterparty_rule(
                rule, source_wallet_id, destination_wallet_id
            )
        
        elif rule.rule_type == FraudRuleType.SUSPICIOUS_PATTERN:
            return await self._evaluate_pattern_rule(rule, amount)
        
        elif rule.rule_type == FraudRuleType.GEO_VELOCITY:
            return await self._evaluate_geo_rule(rule, user_id)
        
        elif rule.rule_type == FraudRuleType.ML_SCORE:
            return await self._evaluate_ml_rule(rule, user_id, amount)
        
        return False, {"reason": "Unknown rule type"}
    
    async def _evaluate_velocity_rule(
        self,
        rule: FraudRule,
        user_id: UUID,
        wallet_id: UUID,
    ) -> tuple[bool, Dict[str, Any]]:
        """Evaluate velocity rule."""
        params = rule.parameters
        scope = params.get("scope", "user")
        window = params.get("window_seconds", 60)
        threshold = params.get("threshold", 10)
        
        if scope == "user":
            entity_id = user_id
        elif scope == "wallet":
            entity_id = wallet_id
        else:
            return False, {"error": f"Unknown scope: {scope}"}
        
        count = await self._get_velocity_count(scope, entity_id, window)
        triggered = count > threshold
        
        return triggered, {
            "count": count,
            "threshold": threshold,
            "window_seconds": window,
            "scope": scope,
        }
    
    async def _evaluate_amount_rule(
        self,
        rule: FraudRule,
        user_id: UUID,
        amount: Decimal,
        currency: str,
    ) -> tuple[bool, Dict[str, Any]]:
        """Evaluate amount threshold rule."""
        params = rule.parameters
        threshold_type = params.get("threshold_type", "absolute")
        
        if threshold_type == "absolute":
            threshold = Decimal(str(params.get("threshold_amount", 10000)))
            triggered = amount >= threshold
            evidence = {"amount": str(amount), "threshold": str(threshold)}
        
        elif threshold_type == "percentile":
            percentile = params.get("percentile", 95)
            lookback_days = params.get("lookback_days", 90)
            min_transactions = params.get("min_transactions", 10)
            
            # Query user's historical transactions
            cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
            result = await self.db.execute(
                select(Transaction.amount)
                .where(
                    Transaction.source_wallet_id.in_(
                        select(Wallet.id).where(Wallet.user_id == user_id)
                    ),
                    Transaction.status == "COMPLETED",
                    Transaction.created_at >= cutoff,
                )
                .order_by(Transaction.amount)
            )
            amounts = [row[0] for row in result.fetchall()]
            
            if len(amounts) < min_transactions:
                return False, {"reason": "Insufficient transaction history"}
            
            # Calculate percentile
            index = int(len(amounts) * percentile / 100)
            threshold_value = amounts[min(index, len(amounts) - 1)]
            triggered = amount >= threshold_value
            evidence = {
                "amount": str(amount),
                "percentile": percentile,
                "threshold_value": str(threshold_value),
                "sample_size": len(amounts),
            }
        
        else:
            return False, {"error": f"Unknown threshold type: {threshold_type}"}
        
        return triggered, evidence
    
    async def _evaluate_counterparty_rule(
        self,
        rule: FraudRule,
        source_wallet_id: UUID,
        destination_wallet_id: Optional[UUID],
    ) -> tuple[bool, Dict[str, Any]]:
        """Evaluate counterparty frequency rule."""
        if not destination_wallet_id:
            return False, {"reason": "No destination wallet"}
        
        params = rule.parameters
        window_hours = params.get("window_hours", 24)
        threshold = params.get("threshold", 5)
        
        cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
        
        result = await self.db.execute(
            select(func.count(Transaction.id))
            .where(
                Transaction.source_wallet_id == source_wallet_id,
                Transaction.destination_wallet_id == destination_wallet_id,
                Transaction.type == "TRANSFER_OUT",
                Transaction.status == "COMPLETED",
                Transaction.created_at >= cutoff,
            )
        )
        count = result.scalar() or 0
        
        triggered = count >= threshold
        
        return triggered, {
            "counterparty_transfers": count,
            "threshold": threshold,
            "window_hours": window_hours,
        }
    
    async def _evaluate_pattern_rule(
        self,
        rule: FraudRule,
        amount: Decimal,
    ) -> tuple[bool, Dict[str, Any]]:
        """Evaluate suspicious pattern rule."""
        params = rule.parameters
        triggered_patterns = []
        
        # Round number check
        if "round_thresholds" in params:
            thresholds = params["round_thresholds"]
            tolerance = params.get("tolerance", 0.01)
            
            for threshold in thresholds:
                diff = abs(amount - Decimal(str(threshold))) / Decimal(str(threshold))
                if diff <= Decimal(str(tolerance)):
                    triggered_patterns.append(f"round_number_{threshold}")
        
        # Just under limit check
        if "thresholds" in params:
            thresholds = params["thresholds"]
            tolerance = params.get("tolerance", 10)
            
            for threshold in thresholds:
                if Decimal(str(threshold - tolerance)) <= amount < Decimal(str(threshold)):
                    triggered_patterns.append(f"just_under_{threshold}")
        
        triggered = len(triggered_patterns) > 0
        
        return triggered, {"triggered_patterns": triggered_patterns}
    
    async def _evaluate_geo_rule(
        self,
        rule: FraudRule,
        user_id: UUID,
    ) -> tuple[bool, Dict[str, Any]]:
        """Evaluate geo velocity rule."""
        # This would need IP geolocation data
        # For now, return not triggered
        return False, {"reason": "Geo evaluation not implemented"}
    
    async def _evaluate_ml_rule(
        self,
        rule: FraudRule,
        user_id: UUID,
        amount: Decimal,
    ) -> tuple[bool, Dict[str, Any]]:
        """Evaluate ML score rule (placeholder for future ML integration)."""
        # Placeholder for ML model integration
        return False, {"reason": "ML scoring not implemented"}
    
    def _calculate_risk(self, rule_results: List) -> FraudAssessment:
        """Calculate risk score from rule results."""
        # Sum weights of triggered rules
        triggered_weight = sum(r.weight for r in rule_results if r.triggered)
        total_weight = sum(r.weight for r in rule_results)
        
        # Normalize
        if total_weight > 0:
            normalized_score = triggered_weight / total_weight
        else:
            normalized_score = Decimal("0.000")
        
        # Clamp
        risk_score = min(Decimal("1.000"), max(Decimal("0.000"), normalized_score))
        
        # Determine risk level
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
    
    async def _persist_fraud_event(
        self,
        transaction_id: UUID,
        user_id: UUID,
        wallet_id: UUID,
        assessment: FraudAssessment,
    ) -> UUID:
        """Persist fraud event to database."""
        # Get wallet for user_id if not provided
        wallet_result = await self.db.execute(
            select(Wallet).where(Wallet.id == wallet_id)
        )
        wallet = wallet_result.scalar_one_or_none()
        if wallet:
            user_id = wallet.user_id
        
        event = FraudEvent(
            transaction_id=transaction_id,
            user_id=user_id,
            wallet_id=wallet_id,
            risk_score=assessment.risk_score,
            risk_level=assessment.risk_level,
            triggered_rules=[
                {
                    "rule_id": str(r.rule_id),
                    "rule_code": r.rule_code,
                    "rule_name": r.rule_name,
                    "weight": str(r.weight),
                    "triggered": r.triggered,
                    "evidence": r.evidence,
                }
                for r in assessment.all_rules
            ],
            status=FraudEventStatus.PENDING_REVIEW if assessment.risk_level in (
                FraudRiskLevel.HIGH, FraudRiskLevel.CRITICAL
            ) else FraudEventStatus.APPROVED,
            auto_blocked=assessment.risk_level == FraudRiskLevel.CRITICAL,
        )
        
        self.db.add(event)
        await self.db.flush()
        await self.db.refresh(event)
        
        return event.id
    
    # Admin API Methods
    async def get_fraud_events(
        self,
        risk_level: Optional[FraudRiskLevel] = None,
        status: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[List[FraudEvent], int]:
        """Get fraud events with filters."""
        query = select(FraudEvent).order_by(FraudEvent.created_at.desc())
        
        if risk_level:
            query = query.where(FraudEvent.risk_level == risk_level)
        if status:
            query = query.where(FraudEvent.status == status)
        
        # Count total
        count_query = select(func.count()).select_from(query.subquery())
        total = await self.db.scalar(count_query) or 0
        
        # Paginate
        query = query.limit(limit).offset(offset)
        result = await self.db.execute(query)
        events = result.scalars().all()
        
        return events, total
    
    async def review_fraud_event(
        self,
        event_id: UUID,
        reviewer_id: UUID,
        status: FraudEventStatus,
        notes: Optional[str] = None,
    ) -> FraudEvent:
        """Review a fraud event."""
        result = await self.db.execute(
            select(FraudEvent).where(FraudEvent.id == event_id)
        )
        event = result.scalar_one_or_none()
        
        if not event:
            raise FraudError(f"Fraud event not found: {event_id}")
        
        event.status = status
        event.reviewer_id = reviewer_id
        event.reviewed_at = datetime.now(timezone.utc)
        event.review_notes = notes
        
        await self.db.commit()
        await self.db.refresh(event)
        
        return event
    
    async def get_fraud_rules(self) -> List[FraudRule]:
        """Get all fraud rules."""
        result = await self.db.execute(
            select(FraudRule).order_by(FraudRule.priority)
        )
        return result.scalars().all()
    
    async def create_fraud_rule(
        self,
        code: str,
        name: str,
        description: str,
        rule_type: FraudRuleType,
        weight: Decimal,
        parameters: Dict[str, Any],
        active: bool = True,
        priority: int = 100,
    ) -> FraudRule:
        """Create a new fraud rule."""
        rule = FraudRule(
            code=code,
            name=name,
            description=description,
            rule_type=rule_type,
            weight=weight,
            parameters=parameters,
            active=active,
            priority=priority,
        )
        
        self.db.add(rule)
        await self.db.commit()
        await self.db.refresh(rule)
        
        # Invalidate cache
        self._rules_cache = []
        self._cache_timestamp = 0
        
        return rule
    
    async def update_fraud_rule(
        self,
        rule_id: UUID,
        **kwargs,
    ) -> Optional[FraudRule]:
        """Update a fraud rule."""
        result = await self.db.execute(
            select(FraudRule).where(FraudRule.id == rule_id)
        )
        rule = result.scalar_one_or_none()
        
        if not rule:
            return None
        
        for key, value in kwargs.items():
            if hasattr(rule, key):
                setattr(rule, key, value)
        
        rule.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(rule)
        
        # Invalidate cache
        self._rules_cache = []
        self._cache_timestamp = 0
        
        return rule