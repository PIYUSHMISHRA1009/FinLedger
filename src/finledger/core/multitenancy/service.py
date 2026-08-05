"""
FinLedger Multi-tenancy Support

Row-level security and tenant isolation for multi-tenant deployments.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set
from uuid import UUID, uuid4
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import select, func, and_, or_, desc, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from sqlalchemy.orm import relationship

from finledger.db.models import User, Wallet
from finledger.db.database import Base
from sqlalchemy import Column, String, DateTime, Boolean, Integer, ForeignKey, Text, Index, Numeric
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from sqlalchemy.orm import relationship


# =============================================================================
# ENUMS & DATA CLASSES
# =============================================================================

class TenantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DELETED = "DELETED"
    PENDING = "PENDING"


class TenantRole(str, Enum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    MEMBER = "MEMBER"
    VIEWER = "VIEWER"


@dataclass
class Tenant:
    """Tenant/organization configuration."""
    id: UUID
    name: str
    slug: str
    status: TenantStatus
    settings: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class TenantMember:
    """Tenant membership."""
    id: UUID
    tenant_id: UUID
    user_id: UUID
    role: TenantRole
    joined_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    invited_by: Optional[UUID] = None


@dataclass
class TenantSettings:
    """Tenant-specific settings."""
    tenant_id: UUID
    # Security
    mfa_required: bool = False
    session_timeout_minutes: int = 60
    max_failed_login_attempts: int = 5
    
    # Features
    enable_fraud_detection: bool = True
    enable_reconciliation: bool = True
    enable_webhooks: bool = True
    
    # Limits
    max_wallets: int = 100
    max_users: int = 1000
    max_monthly_transactions: int = 100000
    
    # Compliance
    kyc_required: bool = False
    aml_threshold: Decimal = Decimal("10000")
    
    # Branding
    logo_url: Optional[str] = None
    primary_color: str = "#0066CC"
    company_name: Optional[str] = None


# =============================================================================
# DATABASE MODELS
# =============================================================================

from sqlalchemy import Column, String, DateTime, Boolean, Integer, ForeignKey, Text, Index, Numeric, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from sqlalchemy.orm import relationship
from finledger.db.database import Base
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from sqlalchemy import Column, String, DateTime, Boolean, Integer, ForeignKey, Text, Index, Numeric, UniqueConstraint

class TenantModel(Base):
    """Tenant/organization model."""
    __tablename__ = "tenants"
    
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), nullable=False, unique=True, index=True)
    status = Column(String(20), nullable=False, default=TenantStatus.ACTIVE.value, index=True)
    settings = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))
    
    # Relationships
    members = relationship("TenantMemberModel", back_populates="tenant", cascade="all, delete-orphan")
    settings_rel = relationship("TenantSettingsModel", back_populates="tenant", cascade="all, delete-orphan", uselist=False)
    
    __table_args__ = (
        Index("idx_tenant_status", "status"),
    )


class TenantMemberModel(Base):
    """Tenant membership model."""
    __tablename__ = "tenant_members"
    
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), nullable=False, default=TenantRole.MEMBER.value)
    joined_at = Column(DateTime(timezone=True), nullable=False, default=datetime.now(timezone.utc))
    invited_by = Column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    # Relationships
    tenant = relationship("TenantModel", back_populates="members")
    user = relationship("User", foreign_keys=[user_id])
    
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_tenant_user"),
        Index("idx_tenant_member_tenant_role", "tenant_id", "role"),
    )


class TenantSettingsModel(Base):
    """Tenant settings model."""
    __tablename__ = "tenant_settings"
    
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, unique=True)
    
    # Security
    mfa_required = Column(Boolean, default=False)
    session_timeout_minutes = Column(Integer, default=60)
    max_failed_login_attempts = Column(Integer, default=5)
    
    # Features
    enable_fraud_detection = Column(Boolean, default=True)
    enable_reconciliation = Column(Boolean, default=True)
    enable_webhooks = Column(Boolean, default=True)
    
    # Limits
    max_wallets = Column(Integer, default=100)
    max_users = Column(Integer, default=1000)
    max_monthly_transactions = Column(Integer, default=100000)
    
    # Compliance
    kyc_required = Column(Boolean, default=False)
    aml_threshold = Column(Numeric(19, 4), default=Decimal("10000"))
    
    # Branding
    logo_url = Column(String(500), nullable=True)
    primary_color = Column(String(7), default="#0066CC")
    company_name = Column(String(255), nullable=True)
    
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))
    
    # Relationships
    tenant = relationship("TenantModel", back_populates="settings_rel")


# =============================================================================
# TENANT CONTEXT MIDDLEWARE
# =============================================================================

from contextvars import ContextVar
from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer

# Context variable for current tenant
current_tenant: ContextVar[Optional[UUID]] = ContextVar('current_tenant', default=None)
current_tenant_member: ContextVar[Optional[TenantMemberModel]] = ContextVar('current_tenant_member', default=None)


class TenantMiddleware:
    """Middleware to extract and validate tenant context."""
    
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        
        request = Request(scope, receive)
        
        # Extract tenant from header or subdomain
        tenant_slug = request.headers.get("X-Tenant-Slug")
        if not tenant_slug:
            # Try subdomain
            host = request.headers.get("host", "")
            if "." in host:
                potential_slug = host.split(".")[0]
                if potential_slug not in ["www", "api", "admin"]:
                    tenant_slug = potential_slug
        
        if tenant_slug:
            # Validate tenant exists
            # This would be done in dependency injection
            pass
        
        await self.app(scope, receive, send)


def get_current_tenant_id() -> Optional[UUID]:
    """Get current tenant ID from context."""
    return current_tenant.get()


def get_current_tenant_member() -> Optional[UUID]:
    """Get current tenant member ID from context."""
    return current_tenant_member.get()


def set_tenant_context(tenant_id: UUID, member_id: UUID = None):
    """Set tenant context for current request."""
    current_tenant.set(tenant_id)
    if member_id:
        current_tenant_member.set(member_id)


def clear_tenant_context():
    """Clear tenant context."""
    current_tenant.set(None)
    current_tenant_member.set(None)


# =============================================================================
# TENANT SERVICE
# =============================================================================

class TenantService:
    """Service for tenant management."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    # -------------------------------------------------------------------------
    # TENANT CRUD
    # -------------------------------------------------------------------------
    
    async def create_tenant(
        self,
        name: str,
        slug: str,
        owner_id: UUID,
        settings: Optional[Dict[str, Any]] = None,
    ) -> TenantModel:
        """Create a new tenant with owner."""
        # Check slug availability
        result = await self.db.execute(
            select(TenantModel).where(TenantModel.slug == slug)
        )
        if result.scalar_one_or_none():
            raise ValueError(f"Slug '{slug}' already exists")
        
        tenant = TenantModel(
            name=name,
            slug=slug,
            status=TenantStatus.ACTIVE,
            settings=settings or {},
        )
        
        self.db.add(tenant)
        await self.db.flush()
        
        # Create owner membership
        member = TenantMemberModel(
            tenant_id=tenant.id,
            user_id=owner_id,
            role=TenantRole.OWNER,
        )
        self.db.add(member)
        
        # Create default settings
        settings_model = TenantSettingsModel(tenant_id=tenant.id)
        self.db.add(settings_model)
        
        await self.db.commit()
        await self.db.refresh(tenant)
        
        return tenant
    
    async def get_tenant(self, tenant_id: UUID) -> Optional[TenantModel]:
        """Get tenant by ID."""
        result = await self.db.execute(
            select(TenantModel).where(TenantModel.id == tenant_id)
        )
        return result.scalar_one_or_none()
    
    async def get_tenant_by_slug(self, slug: str) -> Optional[TenantModel]:
        """Get tenant by slug."""
        result = await self.db.execute(
            select(TenantModel).where(TenantModel.slug == slug)
        )
        return result.scalar_one_or_none()
    
    async def list_tenants(
        self,
        status: Optional[TenantStatus] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[List[TenantModel], int]:
        """List tenants with pagination."""
        query = select(TenantModel)
        
        if status:
            query = query.where(TenantModel.status == status)
        
        count_query = select(func.count()).select_from(query.subquery())
        total = await self.db.scalar(count_query) or 0
        
        query = query.order_by(desc(TenantModel.created_at)).limit(limit).offset(offset)
        result = await self.db.execute(query)
        tenants = result.scalars().all()
        
        return list(tenants), total
    
    async def update_tenant(
        self,
        tenant_id: UUID,
        name: Optional[str] = None,
        status: Optional[TenantStatus] = None,
        settings: Optional[Dict[str, Any]] = None,
    ) -> Optional[TenantModel]:
        """Update tenant."""
        result = await self.db.execute(
            select(TenantModel).where(TenantModel.id == tenant_id)
        )
        tenant = result.scalar_one_or_none()
        
        if not tenant:
            return None
        
        if name:
            tenant.name = name
        if status:
            tenant.status = status
        if settings is not None:
            tenant.settings = settings
        
        tenant.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(tenant)
        return tenant
    
    # -------------------------------------------------------------------------
    # MEMBER MANAGEMENT
    # -------------------------------------------------------------------------
    
    async def add_member(
        self,
        tenant_id: UUID,
        user_id: UUID,
        role: TenantRole,
        invited_by: UUID,
    ) -> TenantMemberModel:
        """Add member to tenant."""
        # Check tenant exists
        tenant = await self.get_tenant(tenant_id)
        if not tenant:
            raise ValueError("Tenant not found")
        
        if tenant.status != TenantStatus.ACTIVE:
            raise ValueError("Cannot add member to inactive tenant")
        
        # Check user not already member
        existing = await self.db.execute(
            select(TenantMemberModel)
            .where(
                TenantMemberModel.tenant_id == tenant_id,
                TenantMemberModel.user_id == user_id,
            )
        )
        if existing.scalar_one_or_none():
            raise ValueError("User is already a member")
        
        member = TenantMemberModel(
            tenant_id=tenant_id,
            user_id=user_id,
            role=role,
            invited_by=invited_by,
        )
        
        self.db.add(member)
        await self.db.commit()
        await self.db.refresh(member)
        
        return member
    
    async def remove_member(
        self,
        tenant_id: UUID,
        user_id: UUID,
        removed_by: UUID,
    ) -> bool:
        """Remove member from tenant."""
        result = await self.db.execute(
            select(TenantMemberModel)
            .where(
                TenantMemberModel.tenant_id == tenant_id,
                TenantMemberModel.user_id == user_id,
            )
        )
        member = result.scalar_one_or_none()
        
        if not member:
            return False
        
        # Prevent removing owner
        if member.role == TenantRole.OWNER:
            raise ValueError("Cannot remove owner")
        
        # Prevent self-removal unless admin
        # Would need to check remover's role
        
        await self.db.delete(member)
        await self.db.commit()
        return True
    
    async def update_member_role(
        self,
        tenant_id: UUID,
        user_id: UUID,
        new_role: TenantRole,
        updated_by: UUID,
    ) -> Optional[TenantMemberModel]:
        """Update member role."""
        result = await self.db.execute(
            select(TenantMemberModel)
            .where(
                TenantMemberModel.tenant_id == tenant_id,
                TenantMemberModel.user_id == user_id,
            )
        )
        member = result.scalar_one_or_none()
        
        if not member:
            return None
        
        # Prevent demoting owner
        if member.role == TenantRole.OWNER and new_role != TenantRole.OWNER:
            raise ValueError("Cannot change owner role")
        
        member.role = new_role
        await self.db.commit()
        await self.db.refresh(member)
        return member
    
    async def list_members(
        self,
        tenant_id: UUID,
        role: Optional[TenantRole] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[List[TenantMemberModel], int]:
        """List tenant members."""
        query = select(TenantMemberModel).where(TenantMemberModel.tenant_id == tenant_id)
        
        if role:
            query = query.where(TenantMemberModel.role == role)
        
        count_query = select(func.count()).select_from(query.subquery())
        total = await self.db.scalar(count_query) or 0
        
        query = query.order_by(desc(TenantMemberModel.joined_at)).limit(limit).offset(offset)
        result = await self.db.execute(query)
        members = result.scalars().all()
        
        return list(members), total
    
    # -------------------------------------------------------------------------
    # SETTINGS
    # -------------------------------------------------------------------------
    
    async def get_settings(self, tenant_id: UUID) -> Optional[TenantSettingsModel]:
        """Get tenant settings."""
        result = await self.db.execute(
            select(TenantSettingsModel).where(TenantSettingsModel.tenant_id == tenant_id)
        )
        return result.scalar_one_or_none()
    
    async def update_settings(
        self,
        tenant_id: UUID,
        settings: Dict[str, Any],
    ) -> Optional[TenantSettingsModel]:
        """Update tenant settings."""
        result = await self.db.execute(
            select(TenantSettingsModel).where(TenantSettingsModel.tenant_id == tenant_id)
        )
        settings_model = result.scalar_one_or_none()
        
        if not settings_model:
            settings_model = TenantSettingsModel(tenant_id=tenant_id)
            self.db.add(settings_model)
        
        # Update fields
        for key, value in settings.items():
            if hasattr(settings_model, key):
                setattr(settings_model, key, value)
        
        settings_model.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(settings_model)
        
        return settings_model
    
    # -------------------------------------------------------------------------
    # ROW-LEVEL SECURITY HELPERS
    # -------------------------------------------------------------------------
    
    @staticmethod
    def add_tenant_filter(query, tenant_id: UUID):
        """Add tenant filter to query for RLS."""
        return query.where(Wallet.tenant_id == tenant_id)
    
    @staticmethod
    def add_tenant_filter_transactions(query, tenant_id: UUID):
        """Add tenant filter to transaction query."""
        return query.where(
            or_(
                Transaction.source_wallet_id.in_(
                    select(Wallet.id).where(Wallet.tenant_id == tenant_id)
                ),
                Transaction.destination_wallet_id.in_(
                    select(Wallet.id).where(Wallet.tenant_id == tenant_id)
                ),
            )
        )


# =============================================================================
# DEPENDENCY INJECTION
# =============================================================================

async def get_tenant_service(db: AsyncSession = Depends(get_db)) -> TenantService:
    """Get tenant service."""
    return TenantService(db)


async def get_current_tenant(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TenantModel:
    """Get current tenant from request context."""
    tenant_slug = request.headers.get("X-Tenant-Slug")
    if not tenant_slug:
        # Try subdomain
        host = request.headers.get("host", "")
        if "." in host:
            potential_slug = host.split(".")[0]
            if potential_slug not in ["www", "api", "admin"]:
                tenant_slug = potential_slug
    
    if not tenant_slug:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "TENANT_REQUIRED", "message": "Tenant slug required"},
        )
    
    tenant = await db.execute(
        select(TenantModel).where(TenantModel.slug == tenant_slug)
    )
    tenant = tenant.scalar_one_or_none()
    
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "TENANT_NOT_FOUND", "message": "Tenant not found"},
        )
    
    if tenant.status != TenantStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "TENANT_INACTIVE", "message": "Tenant is not active"},
        )
    
    return tenant


async def get_current_tenant_member(
    current_user: User = Depends(get_current_user),
    tenant: TenantModel = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> TenantMemberModel:
    """Get current user's membership in current tenant."""
    result = await db.execute(
        select(TenantMemberModel)
        .where(
            TenantMemberModel.tenant_id == tenant.id,
            TenantMemberModel.user_id == current_user.id,
        )
    )
    member = result.scalar_one_or_none()
    
    if not member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "NOT_MEMBER", "message": "Not a member of this tenant"},
        )
    
    return member


def require_tenant_permission(permission: str):
    """Require specific permission within tenant."""
    async def permission_checker(
        member: TenantMemberModel = Depends(get_current_tenant_member),
    ) -> TenantMemberModel:
        role_permissions = {
            TenantRole.OWNER: [
                "tenant:manage", "tenant:delete", "member:manage", "member:invite",
                "member:remove", "settings:manage", "billing:manage",
            ],
            TenantRole.ADMIN: [
                "member:manage", "member:invite", "member:remove",
                "settings:read", "settings:manage", "wallet:manage",
            ],
            TenantRole.MEMBER: [
                "wallet:read", "wallet:write", "transfer:execute",
                "transaction:read", "ledger:read",
            ],
            TenantRole.VIEWER: [
                "wallet:read", "transaction:read", "ledger:read",
            ],
        }
        
        permissions = role_permissions.get(member.role, [])
        if permission not in permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "FORBIDDEN", "message": f"Requires permission: {permission}"},
            )
        
        return member
    
    return permission_checker