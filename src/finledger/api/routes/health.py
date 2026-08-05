"""
FinLedger API Routes - Health & Metrics
"""

from typing import Dict

from fastapi import APIRouter, Depends, Response
from fastapi.responses import PlainTextResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from finledger.db.database import get_db, db_manager
from finledger.api.config.settings import get_settings
from finledger.api.schemas import HealthResponse, HealthDetail

router = APIRouter(tags=["Health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Basic health check",
    description="Returns basic service health status",
)
async def health_check():
    """Basic liveness probe."""
    settings = get_settings()
    return HealthResponse(
        status="healthy",
        version=settings.APP_VERSION,
        timestamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )


@router.get(
    "/health/live",
    response_model=HealthResponse,
    summary="Liveness probe",
    description="Kubernetes liveness probe endpoint",
)
async def liveness_check():
    """Liveness probe - returns 200 if process is alive."""
    settings = get_settings()
    return HealthResponse(
        status="alive",
        version=settings.APP_VERSION,
        timestamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )


@router.get(
    "/health/ready",
    response_model=HealthDetail,
    summary="Readiness probe",
    description="Kubernetes readiness probe - checks DB and Redis connectivity",
)
async def readiness_check(db: AsyncSession = Depends(get_db)):
    """Readiness probe - checks dependencies."""
    settings = get_settings()
    checks = {}
    overall_ready = True
    
    # Check database
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "healthy"
    except Exception as e:
        checks["database"] = f"unhealthy: {str(e)[:100]}"
        overall_ready = False
    
    # Check Redis (if configured)
    try:
        import redis.asyncio as redis
        redis_client = redis.from_url(settings.REDIS_URL)
        await redis_client.ping()
        await redis_client.close()
        checks["redis"] = "healthy"
    except Exception as e:
        checks["redis"] = f"unhealthy: {str(e)[:100]}"
        overall_ready = False
    
    # Check migrations
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        from alembic.runtime.migration import MigrationContext
        
        alembic_cfg = Config("alembic.ini")
        script = ScriptDirectory.from_config(alembic_cfg)
        
        def get_head_revision():
            return script.get_current_head()
        
        def get_current_revision():
            with db_manager.engine.sync_engine.connect() as conn:
                context = MigrationContext.configure(conn)
                return context.get_current_revision()
        
        head = await db.run_sync(lambda _: get_head_revision())
        current = await db.run_sync(lambda _: get_current_revision())
        
        if head == current:
            checks["migrations"] = "current"
        else:
            checks["migrations"] = f"outdated (head: {head}, current: {current})"
            overall_ready = False
    except Exception as e:
        checks["migrations"] = f"unknown: {str(e)[:100]}"
    
    status_code = 200 if overall_ready else 503
    
    return HealthDetail(
        status="ready" if overall_ready else "not_ready",
        checks=checks,
    )


@router.get(
    "/metrics",
    response_class=PlainTextResponse,
    summary="Prometheus metrics",
    description="Returns Prometheus metrics in text format",
)
async def metrics():
    """Prometheus metrics endpoint."""
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )