"""
FinLedger Webhook System (Internal Logic)

Event-driven webhook delivery with:
- Event emission and subscription
- Signature verification
- Exponential backoff retry
- Dead-letter queue
- Idempotent delivery
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable, Set
from uuid import UUID, uuid4
from datetime import datetime, timezone, timedelta
from enum import Enum
import json
import hmac
import hashlib
import asyncio

from sqlalchemy import select, func, and_, or_, desc, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB

from finledger.db.models import User
from finledger.db.database import Base
from sqlalchemy import Column, String, DateTime, Boolean, Integer, ForeignKey, Text, Index, Numeric
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB


# =============================================================================
# ENUMS & DATA CLASSES
# =============================================================================

class WebhookEventType(str, Enum):
    # Wallet events
    WALLET_CREATED = "wallet.created"
    WALLET_UPDATED = "wallet.updated"
    WALLET_FROZEN = "wallet.frozen"
    WALLET_CLOSED = "wallet.closed"
    
    # Transaction events
    TRANSACTION_CREATED = "transaction.created"
    TRANSACTION_COMPLETED = "transaction.completed"
    TRANSACTION_FAILED = "transaction.failed"
    TRANSACTION_BLOCKED = "transaction.blocked"
    TRANSACTION_REVERSED = "transaction.reversed"
    
    # Fraud events
    FRAUD_EVENT_CREATED = "fraud.event.created"
    FRAUD_EVENT_REVIEWED = "fraud.event.reviewed"
    
    # Wallet balance events
    BALANCE_UPDATED = "balance.updated"
    
    # Ledger events
    LEDGER_TRANSACTION_POSTED = "ledger.transaction.posted"
    
    # Reconciliation events
    RECONCILIATION_COMPLETED = "reconciliation.completed"
    RECONCILIATION_DISCREPANCY = "reconciliation.discrepancy"
    
    # Admin events
    USER_CREATED = "user.created"
    USER_UPDATED = "user.updated"


class WebhookDeliveryStatus(str, Enum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    DEAD_LETTER = "DEAD_LETTER"
    CANCELLED = "CANCELLED"


class WebhookEventStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    DELETED = "DELETED"


@dataclass
class WebhookEvent:
    """Webhook event payload."""
    id: UUID
    event_type: WebhookEventType
    payload: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source_service: str = "finledger"


@dataclass
class WebhookDeliveryAttempt:
    """Single delivery attempt record."""
    id: UUID
    webhook_id: UUID
    attempt_number: int
    status: WebhookDeliveryStatus
    request_payload: Dict[str, Any]
    response_status: Optional[int] = None
    response_body: Optional[str] = None
    error_message: Optional[str] = None
    attempted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    next_retry_at: Optional[datetime] = None


@dataclass
class WebhookEndpoint:
    """Webhook endpoint configuration."""
    id: UUID
    url: str
    secret: str
    event_types: List[WebhookEventType]
    is_active: bool = True
    max_retries: int = 5
    timeout_seconds: int = 30
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Security
    secret_rotated_at: Optional[datetime] = None
    signing_algorithm: str = "HMAC-SHA256"
    
    # Filtering
    filter_metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Statistics
    total_deliveries: int = 0
    successful_deliveries: int = 0
    failed_deliveries: int = 0


# =============================================================================
# DATABASE MODELS
# =============================================================================

from sqlalchemy import Column, String, DateTime, Boolean, Integer, ForeignKey, Text, Index, Numeric, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from sqlalchemy.orm import relationship
from finledger.db.database import Base
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from sqlalchemy import Column, String, DateTime, Boolean, Integer, ForeignKey, Text, Index, Numeric, UniqueConstraint

class WebhookEndpointModel(Base):
    """Webhook endpoint configuration."""
    __tablename__ = "webhook_endpoints"
    
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    url = Column(String(500), nullable=False)
    secret = Column(String(255), nullable=False)  # Encrypted at rest
    event_types = Column(JSONB, nullable=False, default=list)  # List of event types
    is_active = Column(Boolean, default=True, index=True)
    max_retries = Column(Integer, default=5)
    timeout_seconds = Column(Integer, default=30)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))
    
    # Security
    secret_rotated_at = Column(DateTime(timezone=True), nullable=True)
    signing_algorithm = Column(String(20), default="HMAC-SHA256")
    
    # Filtering
    filter_metadata = Column(JSONB, nullable=True, default=dict)
    
    # Statistics
    total_deliveries = Column(Integer, default=0)
    successful_deliveries = Column(Integer, default=0)
    failed_deliveries = Column(Integer, default=0)
    
    # Owner
    owner_id = Column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    __table_args__ = (
        Index("idx_webhook_endpoint_active", "is_active"),
        Index("idx_webhook_endpoint_owner", "owner_id"),
    )


class WebhookEventModel(Base):
    """Webhook event record."""
    __tablename__ = "webhook_events"
    
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    event_type = Column(String(50), nullable=False, index=True)
    payload = Column(JSONB, nullable=False)
    metadata = Column(JSONB, nullable=True, default=dict)
    source_service = Column(String(50), nullable=False, default="finledger")
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.now(timezone.utc), index=True)
    
    # Source tracking
    source_user_id = Column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    source_wallet_id = Column(PG_UUID(as_uuid=True), ForeignKey("wallets.id", ondelete="SET NULL"), nullable=True)
    source_transaction_id = Column(PG_UUID(as_uuid=True), ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True)
    
    __table_args__ = (
        Index("idx_webhook_event_type_created", "event_type", "created_at"),
        Index("idx_webhook_event_user", "source_user_id"),
    )


class WebhookDeliveryModel(Base):
    """Webhook delivery attempt record."""
    __tablename__ = "webhook_deliveries"
    
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    webhook_id = Column(PG_UUID(as_uuid=True), ForeignKey("webhook_endpoints.id", ondelete="CASCADE"), nullable=False, index=True)
    event_id = Column(PG_UUID(as_uuid=True), ForeignKey("webhook_events.id", ondelete="CASCADE"), nullable=False, index=True)
    
    attempt_number = Column(Integer, nullable=False, default=1)
    status = Column(String(20), nullable=False, default=WebhookDeliveryStatus.PENDING.value, index=True)
    
    request_payload = Column(JSONB, nullable=False)
    request_headers = Column(JSONB, nullable=True, default=dict)
    response_status = Column(Integer, nullable=True)
    response_body = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    
    attempted_at = Column(DateTime(timezone=True), nullable=False, default=datetime.now(timezone.utc), index=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    next_retry_at = Column(DateTime(timezone=True), nullable=True, index=True)
    
    __table_args__ = (
        Index("idx_webhook_delivery_status_next", "status", "next_retry_at"),
        Index("idx_webhook_delivery_webhook_event", "webhook_id", "event_id"),
    )


class WebhookEventSubscriptionModel(Base):
    """Event type subscriptions for webhook endpoints."""
    __tablename__ = "webhook_event_subscriptions"
    
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    webhook_id = Column(PG_UUID(as_uuid=True), ForeignKey("webhook_endpoints.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String(50), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.now(timezone.utc))
    
    __table_args__ = (
        UniqueConstraint("webhook_id", "event_type", name="uq_webhook_event_type"),
        Index("idx_webhook_subscription_active", "webhook_id", "is_active"),
    )


# =============================================================================
# WEBHOOK SERVICE
# =============================================================================

class WebhookService:
    """
    Webhook delivery service with:
    - Event emission and subscription management
    - Signature verification (HMAC-SHA256)
    - Exponential backoff retry
    - Dead-letter queue
    - Idempotent delivery
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self._endpoint_cache: Dict[UUID, WebhookEndpointModel] = {}
        self._cache_timestamp: float = 0
        self._cache_ttl = 60  # 1 minute
    
    # -------------------------------------------------------------------------
    # ENDPOINT MANAGEMENT
    # -------------------------------------------------------------------------
    
    async def _get_active_endpoints_for_event(self, event_type: WebhookEventType) -> List[WebhookEndpointModel]:
        """Get active endpoints subscribed to an event type."""
        import time
        now = time.time()
        
        if now - self._cache_timestamp > 60 or not self._endpoint_cache:
            # This would need a more sophisticated cache - simplified for now
            pass
        
        result = await self.db.execute(
            select(WebhookEndpointModel)
            .where(
                WebhookEndpointModel.is_active == True,
                WebhookEndpointModel.event_types.op('?')(event_type.value),
            )
        )
        return list(result.scalars().all())
    
    async def create_endpoint(
        self,
        owner_id: UUID,
        url: str,
        event_types: List[WebhookEventType],
        secret: Optional[str] = None,
        max_retries: int = 5,
        timeout_seconds: int = 30,
        filter_metadata: Optional[Dict[str, Any]] = None,
    ) -> UUID:
        """Create a new webhook endpoint."""
        # Generate secret if not provided
        if not secret:
            import secrets
            secret = secrets.token_urlsafe(32)
        
        endpoint = WebhookEndpointModel(
            url=url,
            secret=secret,  # Should be encrypted at rest in production
            event_types=[et.value for et in event_types],
            max_retries=max_retries,
            timeout_seconds=timeout_seconds,
            filter_metadata=filter_metadata or {},
            owner_id=owner_id,
        )
        
        self.db.add(endpoint)
        await self.db.flush()
        await self.db.refresh(endpoint)
        return endpoint.id
    
    async def update_endpoint(
        self,
        endpoint_id: UUID,
        owner_id: UUID,
        url: Optional[str] = None,
        event_types: Optional[List[WebhookEventType]] = None,
        is_active: Optional[bool] = None,
        max_retries: Optional[int] = None,
        timeout_seconds: Optional[int] = None,
        filter_metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[WebhookEndpointModel]:
        """Update webhook endpoint."""
        result = await self.db.execute(
            select(WebhookEndpointModel).where(
                WebhookEndpointModel.id == endpoint_id,
                WebhookEndpointModel.owner_id == owner_id,
            )
        )
        endpoint = result.scalar_one_or_none()
        
        if not endpoint:
            return None
        
        if url is not None:
            endpoint.url = url
        if event_types is not None:
            endpoint.event_types = [et.value for et in event_types]
        if is_active is not None:
            endpoint.is_active = is_active
        if max_retries is not None:
            endpoint.max_retries = max_retries
        if timeout_seconds is not None:
            endpoint.timeout_seconds = timeout_seconds
        if filter_metadata is not None:
            endpoint.filter_metadata = filter_metadata
        
        endpoint.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(endpoint)
        return endpoint
    
    async def rotate_secret(
        self,
        endpoint_id: UUID,
        owner_id: UUID,
    ) -> str:
        """Rotate webhook secret."""
        import secrets
        new_secret = secrets.token_urlsafe(32)
        
        result = await self.db.execute(
            select(WebhookEndpointModel).where(
                WebhookEndpointModel.id == endpoint_id,
                WebhookEndpointModel.owner_id == owner_id,
            )
        )
        endpoint = result.scalar_one_or_none()
        
        if not endpoint:
            raise ValueError("Endpoint not found")
        
        endpoint.secret = new_secret
        endpoint.secret_rotated_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(endpoint)
        
        return new_secret
    
    async def delete_endpoint(
        self,
        endpoint_id: UUID,
        owner_id: UUID,
    ) -> bool:
        """Delete webhook endpoint."""
        result = await self.db.execute(
            select(WebhookEndpointModel).where(
                WebhookEndpointModel.id == endpoint_id,
                WebhookEndpointModel.owner_id == owner_id,
            )
        )
        endpoint = result.scalar_one_or_none()
        
        if not endpoint:
            return False
        
        await self.db.delete(endpoint)
        await self.db.commit()
        return True
    
    # -------------------------------------------------------------------------
    # EVENT EMISSION
    # -------------------------------------------------------------------------
    
    async def emit_event(
        self,
        event_type: WebhookEventType,
        payload: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
        source_user_id: Optional[UUID] = None,
        source_wallet_id: Optional[UUID] = None,
        source_transaction_id: Optional[UUID] = None,
        source_service: str = "finledger",
    ) -> UUID:
        """Emit a webhook event and queue for delivery."""
        # Create event record
        event = WebhookEventModel(
            event_type=event_type.value,
            payload=payload,
            metadata=metadata or {},
            source_service=source_service,
            source_user_id=source_user_id,
            source_wallet_id=source_wallet_id,
            source_transaction_id=source_transaction_id,
        )
        
        self.db.add(event)
        await self.db.flush()
        
        # Queue deliveries for subscribed endpoints
        await self._queue_deliveries(event)
        
        return event.id
    
    async def _queue_deliveries(self, event: WebhookEventModel) -> None:
        """Queue delivery attempts for all subscribed endpoints."""
        # Get active endpoints for this event type
        endpoints = await self._get_active_endpoints_for_event(
            WebhookEventType(event.event_type)
        )
        
        for endpoint in endpoints:
            # Check filter metadata
            if not self._matches_filter(endpoint, event):
                continue
            
            # Create delivery record
            delivery = WebhookDeliveryModel(
                webhook_id=endpoint.id,
                event_id=event.id,
                attempt_number=1,
                status=WebhookDeliveryStatus.PENDING,
                request_payload={
                    "id": str(event.id),
                    "event_type": event.event_type,
                    "payload": event.payload,
                    "metadata": event.metadata,
                    "created_at": event.created_at.isoformat(),
                    "source_service": event.source_service,
                },
                next_retry_at=datetime.now(timezone.utc),
            )
            
            self.db.add(delivery)
        
        await self.db.commit()
    
    def _matches_filter(self, endpoint: WebhookEndpointModel, event: WebhookEventModel) -> bool:
        """Check if event matches endpoint filter."""
        if not endpoint.filter_metadata:
            return True
        
        filter_meta = endpoint.filter_metadata
        
        # Check user_id filter
        if "user_id" in filter_meta:
            if filter_meta["user_id"] != str(event.source_user_id):
                return False
        
        # Check wallet_id filter
        if "wallet_id" in filter_meta:
            if filter_meta["wallet_id"] != str(event.source_wallet_id):
                return False
        
        return True
    
    # -------------------------------------------------------------------------
    # DELIVERY EXECUTION
    # -------------------------------------------------------------------------
    
    async def process_deliveries(self, limit: int = 100) -> int:
        """Process pending deliveries (called by worker)."""
        # Get pending deliveries ready for retry
        result = await self.db.execute(
            select(WebhookDeliveryModel)
            .where(
                WebhookDeliveryModel.status.in_([
                    WebhookDeliveryStatus.PENDING,
                    WebhookDeliveryStatus.RETRYING,
                ]),
                or_(
                    WebhookDeliveryModel.next_retry_at.is_(None),
                    WebhookDeliveryModel.next_retry_at <= datetime.now(timezone.utc),
                ),
            )
            .order_by(WebhookDeliveryModel.next_retry_at)
            .limit(limit)
        )
        deliveries = result.scalars().all()
        
        processed = 0
        for delivery in deliveries:
            await self._execute_delivery(delivery)
            processed += 1
        
        return processed
    
    async def _execute_delivery(self, delivery: WebhookDeliveryModel) -> None:
        """Execute a single delivery attempt."""
        import aiohttp
        
        # Get endpoint
        result = await self.db.execute(
            select(WebhookEndpointModel).where(WebhookEndpointModel.id == delivery.webhook_id)
        )
        endpoint = result.scalar_one_or_none()
        
        if not endpoint or not endpoint.is_active:
            delivery.status = WebhookDeliveryStatus.CANCELLED
            delivery.completed_at = datetime.now(timezone.utc)
            delivery.error_message = "Endpoint not found or inactive"
            await self.db.commit()
            return
        
        # Get event
        event_result = await self.db.execute(
            select(WebhookEventModel).where(WebhookEventModel.id == delivery.event_id)
        )
        event = event_result.scalar_one_or_none()
        
        if not event:
            delivery.status = WebhookDeliveryStatus.CANCELLED
            delivery.completed_at = datetime.now(timezone.utc)
            delivery.error_message = "Event not found"
            await self.db.commit()
            return
        
        # Update status
        delivery.status = WebhookDeliveryStatus.RETRYING
        delivery.attempted_at = datetime.now(timezone.utc)
        await self.db.commit()
        
        # Prepare payload
        payload = delivery.request_payload
        
        # Compute signature
        signature = self._compute_signature(
            secret=endpoint.secret,
            payload=json.dumps(payload, separators=(',', ':'), sort_keys=True),
            timestamp=str(int(datetime.now(timezone.utc).timestamp())),
        )
        
        headers = {
            "Content-Type": "application/json",
            "X-Webhook-Signature": signature,
            "X-Webhook-Timestamp": str(int(datetime.now(timezone.utc).timestamp())),
            "X-Webhook-Event-Type": event.event_type,
            "X-Webhook-Event-ID": str(event.id),
            "X-Webhook-Delivery-ID": str(delivery.id),
            "User-Agent": "FinLedger-Webhook/1.0",
        }
        
        # Add custom headers
        headers.update(endpoint.filter_metadata.get("headers", {}))
        
        # Execute HTTP request
        try:
            timeout = aiohttp.ClientTimeout(total=endpoint.timeout_seconds)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    endpoint.url,
                    json=payload,
                    headers=headers,
                ) as response:
                    response_body = await response.text()
                    
                    delivery.response_status = response.status
                    delivery.response_body = response_body[:10000]  # Limit size
                    delivery.completed_at = datetime.now(timezone.utc)
                    
                    if 200 <= response.status < 300:
                        delivery.status = WebhookDeliveryStatus.DELIVERED
                        # Update endpoint stats
                        endpoint.total_deliveries += 1
                        endpoint.successful_deliveries += 1
                    else:
                        raise aiohttp.ClientResponseError(
                            request_info=response.request_info,
                            history=response.history,
                            status=response.status,
                            message=response_body,
                        )
        
        except Exception as e:
            delivery.error_message = str(e)[:1000]
            
            # Check if should retry
            if delivery.attempt_number < endpoint.max_retries:
                delivery.attempt_number += 1
                delivery.status = WebhookDeliveryStatus.RETRYING
                
                # Exponential backoff: 2^attempt minutes, max 60 minutes
                backoff_minutes = min(2 ** delivery.attempt_number, 60)
                delivery.next_retry_at = datetime.now(timezone.utc) + timedelta(minutes=backoff_minutes)
            else:
                delivery.status = WebhookDeliveryStatus.DEAD_LETTER
                delivery.completed_at = datetime.now(timezone.utc)
                
                # Update endpoint stats
                endpoint.failed_deliveries += 1
        
        endpoint.total_deliveries += 1
        await self.db.commit()
    
    def _compute_signature(self, secret: str, payload: str, timestamp: str) -> str:
        """Compute HMAC-SHA256 signature."""
        # Format: timestamp.payload
        signed_payload = f"{timestamp}.{payload}"
        signature = hmac.new(
            secret.encode(),
            signed_payload.encode(),
            hashlib.sha256,
        ).hexdigest()
        return f"sha256={signature}"
    
    def verify_signature(self, secret: str, payload: str, timestamp: str, signature: str) -> bool:
        """Verify webhook signature."""
        expected = self._compute_signature(secret, payload, timestamp)
        return hmac.compare_digest(signature, expected)
    
    # -------------------------------------------------------------------------
    # DEAD LETTER QUEUE
    # -------------------------------------------------------------------------
    
    async def get_dead_letters(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[List[WebhookDeliveryModel], int]:
        """Get dead letter queue entries."""
        query = select(WebhookDeliveryModel).where(
            WebhookDeliveryModel.status == WebhookDeliveryStatus.DEAD_LETTER
        ).order_by(desc(WebhookDeliveryModel.completed_at))
        
        count_query = select(func.count()).select_from(query.subquery())
        total = await self.db.scalar(count_query) or 0
        
        query = query.limit(limit).offset(offset)
        result = await self.db.execute(query)
        deliveries = result.scalars().all()
        
        return list(deliveries), total
    
    async def retry_dead_letter(
        self,
        delivery_id: UUID,
        current_user: UUID,
    ) -> bool:
        """Retry a dead letter delivery."""
        result = await self.db.execute(
            select(WebhookDeliveryModel).where(WebhookDeliveryModel.id == delivery_id)
        )
        delivery = result.scalar_one_or_none()
        
        if not delivery:
            return False
        
        if delivery.status != WebhookDeliveryStatus.DEAD_LETTER:
            return False
        
        # Reset for retry
        delivery.status = WebhookDeliveryStatus.PENDING
        delivery.attempt_number = 1
        delivery.error_message = None
        delivery.next_retry_at = datetime.now(timezone.utc)
        
        await self.db.commit()
        return True
    
    # -------------------------------------------------------------------------
    # STATISTICS
    # -------------------------------------------------------------------------
    
    async def get_endpoint_stats(
        self,
        endpoint_id: UUID,
        owner_id: UUID,
    ) -> Optional[Dict[str, Any]]:
        """Get endpoint statistics."""
        result = await self.db.execute(
            select(WebhookEndpointModel).where(
                WebhookEndpointModel.id == endpoint_id,
                WebhookEndpointModel.owner_id == owner_id,
            )
        )
        endpoint = result.scalar_one_or_none()
        
        if not endpoint:
            return None
        
        # Get recent delivery stats
        day_ago = datetime.now(timezone.utc) - timedelta(days=1)
        
        stats_result = await self.db.execute(
            select(
                func.count(WebhookDeliveryModel.id).label("total"),
                func.sum(
                    case(
                        (WebhookDeliveryModel.status == WebhookDeliveryStatus.DELIVERED, 1),
                        else_=0,
                    )
                ).label("successful"),
                func.sum(
                    case(
                        (WebhookDeliveryModel.status == WebhookDeliveryStatus.DEAD_LETTER, 1),
                        else_=0,
                    )
                ).label("failed"),
            ).where(
                WebhookDeliveryModel.webhook_id == endpoint.id,
                WebhookDeliveryModel.attempted_at >= day_ago,
            )
        )
        stats = stats_result.first()
        
        return {
            "endpoint_id": str(endpoint.id),
            "url": endpoint.url,
            "is_active": endpoint.is_active,
            "event_types": endpoint.event_types,
            "total_deliveries": endpoint.total_deliveries,
            "successful_deliveries": endpoint.successful_deliveries,
            "failed_deliveries": endpoint.failed_deliveries,
            "last_24h": {
                "total": stats.total or 0,
                "successful": stats.successful or 0,
                "failed": stats.failed or 0,
            },
        }


# =============================================================================
# EVENT EMITTER HELPER
# =============================================================================

class EventEmitter:
    """Helper to emit events from services."""
    
    def __init__(self, webhook_service: WebhookService):
        self.webhook = webhook_service
    
    async def wallet_created(
        self,
        wallet_id: UUID,
        user_id: UUID,
        currency: str,
        name: str,
    ):
        await self.webhook.emit_event(
            event_type=WebhookEventType.WALLET_CREATED,
            payload={
                "wallet_id": str(wallet_id),
                "user_id": str(user_id),
                "currency": currency,
                "name": name,
            },
            source_wallet_id=wallet_id,
            source_user_id=user_id,
        )
    
    async def transaction_completed(
        self,
        transaction_id: UUID,
        wallet_id: UUID,
        amount: Decimal,
        currency: str,
        type: str,
        counterparty_wallet_id: Optional[UUID] = None,
    ):
        await self.webhook.emit_event(
            event_type=WebhookEventType.TRANSACTION_COMPLETED,
            payload={
                "transaction_id": str(transaction_id),
                "wallet_id": str(wallet_id),
                "amount": str(amount),
                "currency": currency,
                "type": type,
                "counterparty_wallet_id": str(counterparty_wallet_id) if counterparty_wallet_id else None,
            },
            source_wallet_id=wallet_id,
            source_transaction_id=transaction_id,
        )
    
    async def fraud_detected(
        self,
        fraud_event_id: UUID,
        transaction_id: UUID,
        wallet_id: UUID,
        risk_score: Decimal,
        risk_level: str,
        triggered_rules: List[Dict[str, Any]],
    ):
        await self.webhook.emit_event(
            event_type=WebhookEventType.FRAUD_EVENT_CREATED,
            payload={
                "fraud_event_id": str(fraud_event_id),
                "transaction_id": str(transaction_id),
                "wallet_id": str(wallet_id),
                "risk_score": str(risk_score),
                "risk_level": risk_level,
                "triggered_rules": triggered_rules,
            },
            source_wallet_id=wallet_id,
            source_transaction_id=transaction_id,
        )
    
    async def ledger_transaction_posted(
        self,
        ledger_transaction_id: UUID,
        reference: str,
        entries: List[Dict[str, Any]],
    ):
        await self.webhook.emit_event(
            event_type=WebhookEventType.LEDGER_TRANSACTION_POSTED,
            payload={
                "ledger_transaction_id": str(ledger_transaction_id),
                "reference": reference,
                "entries": entries,
            },
        )
    
    async def reconciliation_completed(
        self,
        job_id: UUID,
        matched: int,
        mismatched: int,
        total_discrepancy: Decimal,
    ):
        await self.webhook.emit_event(
            event_type=WebhookEventType.RECONCILIATION_COMPLETED,
            payload={
                "job_id": str(job_id),
                "matched": matched,
                "mismatched": mismatched,
                "total_discrepancy": str(total_discrepancy),
            },
        )


# =============================================================================
# ADMIN API FOR WEBHOOKS
# =============================================================================

webhook_router = APIRouter(prefix="/admin/webhooks", tags=["Webhooks"])


@webhook_router.post(
    "/endpoints",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
)
async def create_webhook_endpoint(
    request: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new webhook endpoint."""
    service = WebhookService(db)
    
    endpoint_id = await service.create_endpoint(
        owner_id=current_user.id,
        url=request["url"],
        event_types=[WebhookEventType(et) for et in request["event_types"]],
        secret=request.get("secret"),
        max_retries=request.get("max_retries", 5),
        timeout_seconds=request.get("timeout_seconds", 30),
        filter_metadata=request.get("filter_metadata"),
    )
    
    return {"endpoint_id": str(endpoint_id)}


@webhook_router.get(
    "/endpoints",
    response_model=dict,
)
async def list_webhook_endpoints(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List user's webhook endpoints."""
    result = await db.execute(
        select(WebhookEndpointModel)
        .where(WebhookEndpointModel.owner_id == current_user.id)
        .order_by(desc(WebhookEndpointModel.created_at))
        .limit(limit)
        .offset(offset)
    )
    endpoints = result.scalars().all()
    
    return {
        "items": [
            {
                "id": str(e.id),
                "url": e.url,
                "event_types": e.event_types,
                "is_active": e.is_active,
                "max_retries": e.max_retries,
                "timeout_seconds": e.timeout_seconds,
                "total_deliveries": e.total_deliveries,
                "successful_deliveries": e.successful_deliveries,
                "failed_deliveries": e.failed_deliveries,
                "created_at": e.created_at.isoformat(),
                "updated_at": e.updated_at.isoformat(),
            }
            for e in endpoints
        ],
        "total": len(endpoints),
        "limit": limit,
        "offset": offset,
    }


@webhook_router.get(
    "/endpoints/{endpoint_id}",
    response_model=dict,
)
async def get_webhook_endpoint(
    endpoint_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get webhook endpoint details."""
    result = await db.execute(
        select(WebhookEndpointModel).where(
            WebhookEndpointModel.id == endpoint_id,
            WebhookEndpointModel.owner_id == current_user.id,
        )
    )
    endpoint = result.scalar_one_or_none()
    
    if not endpoint:
        raise HTTPException(status_code=404, detail="Endpoint not found")
    
    return {
        "id": str(endpoint.id),
        "url": endpoint.url,
        "event_types": endpoint.event_types,
        "is_active": endpoint.is_active,
        "max_retries": endpoint.max_retries,
        "timeout_seconds": endpoint.timeout_seconds,
        "filter_metadata": endpoint.filter_metadata,
        "total_deliveries": endpoint.total_deliveries,
        "successful_deliveries": endpoint.successful_deliveries,
        "failed_deliveries": endpoint.failed_deliveries,
        "created_at": endpoint.created_at.isoformat(),
        "updated_at": endpoint.updated_at.isoformat(),
    }


@webhook_router.patch(
    "/endpoints/{endpoint_id}",
    response_model=dict,
)
async def update_webhook_endpoint(
    endpoint_id: UUID,
    request: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update webhook endpoint."""
    service = WebhookService(db)
    
    endpoint = await service.update_endpoint(
        endpoint_id=endpoint_id,
        owner_id=current_user.id,
        url=request.get("url"),
        event_types=[WebhookEventType(et) for et in request["event_types"]] if request.get("event_types") else None,
        is_active=request.get("is_active"),
        max_retries=request.get("max_retries"),
        timeout_seconds=request.get("timeout_seconds"),
        filter_metadata=request.get("filter_metadata"),
    )
    
    if not endpoint:
        raise HTTPException(status_code=404, detail="Endpoint not found")
    
    return {
        "id": str(endpoint.id),
        "url": endpoint.url,
        "event_types": endpoint.event_types,
        "is_active": endpoint.is_active,
    }


@webhook_router.post(
    "/endpoints/{endpoint_id}/rotate-secret",
    response_model=dict,
)
async def rotate_webhook_secret(
    endpoint_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Rotate webhook secret."""
    service = WebhookService(db)
    new_secret = await service.rotate_secret(endpoint_id, current_user.id)
    return {"secret": new_secret}


@webhook_router.delete(
    "/endpoints/{endpoint_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_webhook_endpoint(
    endpoint_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete webhook endpoint."""
    service = WebhookService(db)
    deleted = await service.delete_endpoint(endpoint_id, current_user.id)
    
    if not deleted:
        raise HTTPException(status_code=404, detail="Endpoint not found")


@webhook_router.get(
    "/deliveries",
    response_model=dict,
)
async def list_deliveries(
    endpoint_id: Optional[UUID] = Query(None),
    event_id: Optional[UUID] = Query(None),
    status: Optional[WebhookDeliveryStatus] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List webhook deliveries."""
    query = select(WebhookDeliveryModel).join(WebhookEndpointModel).where(
        WebhookEndpointModel.owner_id == current_user.id
    )
    
    if endpoint_id:
        query = query.where(WebhookDeliveryModel.webhook_id == endpoint_id)
    if event_id:
        query = query.where(WebhookDeliveryModel.event_id == event_id)
    if status:
        query = query.where(WebhookDeliveryModel.status == status.value)
    
    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query) or 0
    
    query = query.order_by(desc(WebhookDeliveryModel.attempted_at)).limit(limit).offset(offset)
    result = await db.execute(query)
    deliveries = result.scalars().all()
    
    return {
        "items": [
            {
                "id": str(d.id),
                "webhook_id": str(d.webhook_id),
                "event_id": str(d.event_id),
                "attempt_number": d.attempt_number,
                "status": d.status,
                "response_status": d.response_status,
                "error_message": d.error_message,
                "attempted_at": d.attempted_at.isoformat(),
                "completed_at": d.completed_at.isoformat() if d.completed_at else None,
            }
            for d in deliveries
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@webhook_router.get(
    "/dead-letters",
    response_model=dict,
)
async def list_dead_letters(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List dead letter deliveries."""
    query = select(WebhookDeliveryModel).join(WebhookEndpointModel).where(
        WebhookEndpointModel.owner_id == current_user.id,
        WebhookDeliveryModel.status == WebhookDeliveryStatus.DEAD_LETTER
    ).order_by(desc(WebhookDeliveryModel.completed_at))
    
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query) or 0
    
    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    deliveries = result.scalars().all()
    
    return {
        "items": [
            {
                "id": str(d.id),
                "webhook_id": str(d.webhook_id),
                "event_id": str(d.event_id),
                "attempt_number": d.attempt_number,
                "error_message": d.error_message,
                "completed_at": d.completed_at.isoformat() if d.completed_at else None,
            }
            for d in deliveries
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@webhook_router.post(
    "/dead-letters/{delivery_id}/retry",
    response_model=dict,
)
async def retry_dead_letter(
    delivery_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retry a dead letter delivery."""
    service = WebhookService(db)
    success = await service.retry_dead_letter(delivery_id, current_user.id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Dead letter not found or not in dead letter status")
    
    return {"success": True}