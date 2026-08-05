"""
FinLedger API Routes - Fraud (Admin/Compliance)
"""

from typing import Optional, List
from uuid import UUID
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from finledger.api.schemas import (
    FraudEventResponse,
    FraudReviewRequest,
    FraudRuleCreateRequest,
    FraudRuleUpdateRequest,
    FraudRuleResponse,
    ErrorResponse,
)
from finledger.api.routes.auth import get_current_user, require_permission, require_role
from finledger.core.fraud.service import FraudService
from finledger.core.exceptions import FraudError
from finledger.db.database import get_db
from finledger.db.models import User, FraudEventStatus, FraudRuleType, FraudRiskLevel

router = APIRouter(prefix="/fraud", tags=["Fraud"])
security = HTTPBearer(auto_error=False)


def get_fraud_service(
    db: AsyncSession = Depends(get_db),
) -> FraudService:
    """Dependency for fraud service."""
    return FraudService(db)


@router.get(
    "/events",
    response_model=dict,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Requires compliance/admin role"},
    },
)
async def list_fraud_events(
    risk_level: Optional[FraudRiskLevel] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_permission("fraud:read")),
    fraud_service: FraudService = Depends(get_fraud_service),
):
    """
    List fraud events with filters (Compliance/Admin only).
    """
    events, total = await fraud_service.get_fraud_events(
        risk_level=risk_level,
        status=status,
        limit=limit,
        offset=offset,
    )
    
    return {
        "items": [FraudEventResponse.model_validate(e) for e in events],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.patch(
    "/events/{event_id}/review",
    response_model=FraudEventResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Requires compliance role"},
        404: {"model": ErrorResponse, "description": "Fraud event not found"},
    },
)
async def review_fraud_event(
    event_id: UUID,
    request: FraudReviewRequest,
    current_user: User = Depends(require_role("COMPLIANCE", "ADMIN")),
    fraud_service: FraudService = Depends(get_fraud_service),
):
    """
    Review a fraud event (Compliance/Admin only).
    """
    try:
        event = await fraud_service.review_fraud_event(
            event_id=event_id,
            reviewer_id=current_user.id,
            status=request.status,
            notes=request.review_notes,
        )
    except FraudError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": str(e)},
        )
    
    return FraudEventResponse.model_validate(event)


@router.get(
    "/rules",
    response_model=List[FraudRuleResponse],
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Requires admin role"},
    },
)
async def list_fraud_rules(
    current_user: User = Depends(require_role("ADMIN")),
    fraud_service: FraudService = Depends(get_fraud_service),
):
    """
    List all fraud rules (Admin only).
    """
    rules = await fraud_service.get_fraud_rules()
    return [FraudRuleResponse.model_validate(r) for r in rules]


@router.post(
    "/rules",
    response_model=FraudRuleResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ErrorResponse, "description": "Validation error"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Requires admin role"},
    },
)
async def create_fraud_rule(
    request: FraudRuleCreateRequest,
    current_user: User = Depends(require_role("ADMIN")),
    fraud_service: FraudService = Depends(get_fraud_service),
):
    """
    Create a new fraud rule (Admin only).
    """
    try:
        rule = await fraud_service.create_fraud_rule(
            code=request.code,
            name=request.name,
            description=request.description or "",
            rule_type=request.rule_type,
            weight=request.weight,
            parameters=request.parameters,
            active=request.active,
            priority=request.priority,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "VALIDATION_ERROR", "message": str(e)},
        )
    
    return FraudRuleResponse.model_validate(rule)


@router.patch(
    "/rules/{rule_id}",
    response_model=FraudRuleResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Requires admin role"},
        404: {"model": ErrorResponse, "description": "Rule not found"},
    },
)
async def update_fraud_rule(
    rule_id: UUID,
    request: FraudRuleUpdateRequest,
    current_user: User = Depends(require_role("ADMIN")),
    fraud_service: FraudService = Depends(get_fraud_service),
):
    """
    Update a fraud rule (Admin only).
    """
    rule = await fraud_service.update_fraud_rule(
        rule_id=rule_id,
        **request.model_dump(exclude_unset=True),
    )
    
    if not rule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Fraud rule not found"},
        )
    
    return FraudRuleResponse.model_validate(rule)