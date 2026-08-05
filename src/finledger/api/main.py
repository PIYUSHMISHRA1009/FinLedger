"""
FinLedger Main Application

FastAPI application factory with all routes, middleware, and configuration.
"""

import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html, get_redoc_html
from fastapi.openapi.utils import get_openapi
from prometheus_client import Counter, Histogram, Gauge, generate_latest
from prometheus_client.exposition import CONTENT_TYPE_LATEST
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from finledger.api.config.settings import get_settings
from finledger.api.routes import auth, wallets, ledger, fraud, health
from finledger.api.routes.auth import get_redis_client, set_redis_client
from finledger.core.auth.rbac import AuthenticationError, PermissionError as AuthPermissionError
from finledger.core.exceptions import (
    FinLedgerError,
    ValidationError,
    InsufficientFundsError,
    WalletNotFoundError,
    WalletFrozenError,
    WalletClosedError,
    CurrencyMismatchError,
    SameWalletTransferError,
    IdempotencyKeyRequiredError,
    IdempotencyKeyConflictError,
    FraudBlockedError,
    AccountLockedError,
    AccountDeactivatedError,
    TokenExpiredError,
    TokenRevokedError,
    TokenReuseError,
    InvalidCredentialsError,
    InsufficientPermissionsError,
    RateLimitError,
)
from finledger.db.database import db_manager, get_db
import structlog


# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


# Prometheus Metrics
http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "path"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

wallet_balance_gauge = Gauge(
    "wallet_balance",
    "Current wallet balance",
    ["wallet_id", "currency", "balance_type"],
)

transaction_total = Counter(
    "transaction_total",
    "Total transactions",
    ["type", "status", "currency"],
)

fraud_risk_score_histogram = Histogram(
    "fraud_risk_score",
    "Fraud risk score distribution",
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)

active_users_gauge = Gauge(
    "active_users",
    "Number of active users",
)

database_connections_gauge = Gauge(
    "database_connections_active",
    "Active database connections",
)


# Redis client (initialized on startup)
redis_client: Optional = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global redis_client
    
    settings = get_settings()
    
    # Startup
    logger.info("Starting FinLedger", version=settings.APP_VERSION, environment=settings.ENVIRONMENT)
    
    # Initialize database
    db_manager.initialize()
    logger.info("Database initialized")
    
    # Initialize Redis
    try:
        import redis.asyncio as redis
        redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        await redis_client.ping()
        set_redis_client(redis_client)
        logger.info("Redis connected")
    except Exception as e:
        logger.warning("Redis connection failed", error=str(e))
        redis_client = None
    
    # Ensure JWT keys exist (dev only)
    from finledger.api.config.settings import ensure_keys_exist
    ensure_keys_exist(settings)
    
    logger.info("FinLedger startup complete")
    
    yield
    
    # Shutdown
    logger.info("Shutting down FinLedger")
    
    if redis_client:
        await redis_client.close()
        logger.info("Redis disconnected")
    
    await db_manager.close()
    logger.info("Database closed")
    
    logger.info("FinLedger shutdown complete")


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    settings = get_settings()
    
    app = FastAPI(
        title="FinLedger API",
        description="Production-grade digital wallet and transaction platform with immutable double-entry ledger",
        version=settings.APP_VERSION,
        docs_url=None,  # Custom docs endpoints
        redoc_url=None,
        openapi_url="/openapi.json" if not settings.is_production else None,
        lifespan=lifespan,
    )
    
    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ALLOW_ORIGINS,
        allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
        allow_methods=settings.CORS_ALLOW_METHODS,
        allow_headers=settings.CORS_ALLOW_HEADERS,
        expose_headers=["X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"],
    )
    
    # Middleware
    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        """Add request ID to all requests and responses."""
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id
        
        # Add to structlog context
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
    
    @app.middleware("http")
    async def logging_middleware(request: Request, call_next):
        """Structured request/response logging."""
        start_time = time.time()
        
        # Log request
        logger.info(
            "request_started",
            method=request.method,
            path=request.url.path,
            query_params=str(request.query_params),
            client_host=request.client.host if request.client else None,
        )
        
        response = await call_next(request)
        
        # Calculate duration
        duration = time.time() - start_time
        
        # Record metrics
        http_requests_total.labels(
            method=request.method,
            path=request.url.path,
            status=response.status_code,
        ).inc()
        
        http_request_duration_seconds.labels(
            method=request.method,
            path=request.url.path,
        ).observe(duration)
        
        # Log response
        logger.info(
            "request_completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round(duration * 1000, 2),
        )
        
        return response
    
    @app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next):
        """Rate limiting middleware."""
        settings = get_settings()
        
        if not settings.RATE_LIMIT_ENABLED:
            return await call_next(request)
        
        # Skip rate limiting for health endpoints
        if request.url.path in ["/health", "/health/live", "/health/ready", "/metrics"]:
            return await call_next(request)
        
        # Get client identifier
        client_ip = request.client.host if request.client else "unknown"
        user_id = getattr(request.state, "user_id", None)
        identifier = f"user:{user_id}" if user_id else f"ip:{client_ip}"
        
        # Check rate limit (simplified - uses Redis)
        if redis_client:
            try:
                key = f"ratelimit:{identifier}"
                current = await redis_client.incr(key)
                if current == 1:
                    await redis_client.expire(key, settings.RATE_LIMIT_WINDOW_SECONDS)
                
                if current > settings.RATE_LIMIT_DEFAULT:
                    return JSONResponse(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        content={
                            "error": {
                                "code": "RATE_LIMITED",
                                "message": "Too many requests",
                                "details": [],
                            }
                        },
                        headers={
                            "X-RateLimit-Limit": str(settings.RATE_LIMIT_DEFAULT),
                            "X-RateLimit-Remaining": "0",
                            "X-RateLimit-Reset": str(int(time.time()) + settings.RATE_LIMIT_WINDOW_SECONDS),
                        },
                    )
                
                # Add rate limit headers
                response = await call_next(request)
                response.headers["X-RateLimit-Limit"] = str(settings.RATE_LIMIT_DEFAULT)
                response.headers["X-RateLimit-Remaining"] = str(max(0, settings.RATE_LIMIT_DEFAULT - current))
                response.headers["X-RateLimit-Reset"] = str(int(time.time()) + settings.RATE_LIMIT_WINDOW_SECONDS)
                return response
            except Exception:
                pass  # Fail open on Redis errors
        
        return await call_next(request)
    
    # Exception Handlers
    @app.exception_handler(FinLedgerError)
    async def finledger_exception_handler(request: Request, exc: FinLedgerError):
        logger.warning(
            "finledger_error",
            code=exc.code,
            message=exc.message,
            details=exc.details,
            path=request.url.path,
        )
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
        )
    
    @app.exception_handler(ValidationError)
    async def validation_exception_handler(request: Request, exc: ValidationError):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": str(exc),
                    "details": [],
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
        )
    
    @app.exception_handler(InsufficientFundsError)
    async def insufficient_funds_handler(request: Request, exc: InsufficientFundsError):
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "error": {
                    "code": "INSUFFICIENT_FUNDS",
                    "message": str(exc),
                    "details": [],
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
        )
    
    @app.exception_handler(WalletNotFoundError)
    async def wallet_not_found_handler(request: Request, exc: WalletNotFoundError):
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "error": {
                    "code": "NOT_FOUND",
                    "message": str(exc),
                    "details": [],
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
        )
    
    @app.exception_handler(WalletFrozenError)
    @app.exception_handler(WalletClosedError)
    @app.exception_handler(CurrencyMismatchError)
    @app.exception_handler(SameWalletTransferError)
    @app.exception_handler(IdempotencyKeyRequiredError)
    @app.exception_handler(IdempotencyKeyConflictError)
    async def wallet_conflict_handler(request: Request, exc: FinLedgerError):
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "error": {
                    "code": exc.code,
                    "message": str(exc),
                    "details": exc.details,
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
        )
    
    @app.exception_handler(FraudBlockedError)
    async def fraud_blocked_handler(request: Request, exc: FraudBlockedError):
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "error": {
                    "code": "FRAUD_BLOCKED",
                    "message": str(exc),
                    "details": exc.details,
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
        )
    
    @app.exception_handler(AuthenticationError)
    @app.exception_handler(TokenExpiredError)
    @app.exception_handler(TokenRevokedError)
    @app.exception_handler(TokenReuseError)
    @app.exception_handler(InvalidCredentialsError)
    @app.exception_handler(AccountLockedError)
    @app.exception_handler(AccountDeactivatedError)
    async def auth_error_handler(request: Request, exc: FinLedgerError):
        status_code = status.HTTP_401_UNAUTHORIZED
        if isinstance(exc, (AccountLockedError, AccountDeactivatedError)):
            status_code = status.HTTP_403_FORBIDDEN
        
        return JSONResponse(
            status_code=status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": str(exc),
                    "details": exc.details,
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
            headers={"WWW-Authenticate": "Bearer"} if status_code == 401 else {},
        )
    
    @app.exception_handler(AuthPermissionError)
    @app.exception_handler(InsufficientPermissionsError)
    async def permission_error_handler(request: Request, exc: FinLedgerError):
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "error": {
                    "code": "FORBIDDEN",
                    "message": str(exc),
                    "details": exc.details,
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
        )
    
    @app.exception_handler(RateLimitError)
    async def rate_limit_handler(request: Request, exc: RateLimitError):
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "error": {
                    "code": "RATE_LIMITED",
                    "message": str(exc),
                    "details": exc.details,
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
        )
    
    @app.exception_handler(RequestValidationError)
    async def pydantic_validation_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Request validation failed",
                    "details": [
                        {"field": ".".join(str(x) for x in error["loc"]), "message": error["msg"]}
                        for error in exc.errors()
                    ],
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
        )
    
    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        logger.exception(
            "unhandled_exception",
            path=request.url.path,
            error=str(exc),
            request_id=getattr(request.state, "request_id", None),
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "An unexpected error occurred",
                    "details": [],
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
        )
    
    # Custom OpenAPI
    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        
        openapi_schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        
        # Add security scheme
        openapi_schema["components"]["securitySchemes"] = {
            "BearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
            },
            "IdempotencyKey": {
                "type": "apiKey",
                "in": "header",
                "name": "Idempotency-Key",
            },
        }
        
        # Apply security globally
        openapi_schema["security"] = [{"BearerAuth": []}]
        
        app.openapi_schema = openapi_schema
        return app.openapi_schema
    
    app.openapi = custom_openapi
    
    # Custom docs
    @app.get("/docs", include_in_schema=False)
    async def custom_swagger_ui_html():
        return get_swagger_ui_html(
            openapi_url=app.openapi_url,
            title=f"{app.title} - Swagger UI",
            swagger_js_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js",
            swagger_css_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css",
        )
    
    @app.get("/redoc", include_in_schema=False)
    async def redoc_html():
        return get_redoc_html(
            openapi_url=app.openapi_url,
            title=f"{app.title} - ReDoc",
            redoc_js_url="https://cdn.jsdelivr.net/npm/redoc@next/bundles/redoc.standalone.js",
        )
    
    # Include routers
    app.include_router(auth.router)
    app.include_router(wallets.router)
    app.include_router(ledger.router)
    app.include_router(fraud.router)
    app.include_router(health.router)
    
    return app


# Create app instance
app = create_app()


if __name__ == "__main__":
    import uvicorn
    settings = get_settings()
    uvicorn.run(
        "finledger.api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
        log_config=None,  # Use structlog
    )