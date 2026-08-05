"""
FinLedger Test Configuration and Fixtures
"""

import asyncio
from collections.abc import AsyncGenerator
from typing import AsyncGenerator as TypedAsyncGenerator
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from finledger.api.main import create_app
from finledger.api.config.settings import Settings
from finledger.db.database import Base, db_manager
from finledger.db.models import User, Wallet, LedgerAccount


# Test settings
TEST_DATABASE_URL = "postgresql+asyncpg://finledger:test@localhost:5432/finledger_test"
TEST_REDIS_URL = "redis://localhost:6379/1"


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def test_settings():
    """Test settings override."""
    return Settings(
        ENVIRONMENT="test",
        DATABASE_URL=TEST_DATABASE_URL,
        REDIS_URL=TEST_REDIS_URL,
        JWT_PRIVATE_KEY_PATH="./keys/jwt_private.pem",
        JWT_PUBLIC_KEY_PATH="./keys/jwt_public.pem",
        JWT_ACCESS_TOKEN_EXPIRE_MINUTES=15,
        JWT_REFRESH_TOKEN_EXPIRE_DAYS=7,
        RATE_LIMIT_ENABLED=False,
        DEBUG=True,
    )


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    """Create test database engine."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    
    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    yield engine
    
    # Cleanup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine) -> TypedAsyncGenerator[AsyncSession, None]:
    """Create a test database session with transaction rollback."""
    async with test_engine.connect() as conn:
        transaction = await conn.begin()
        session = sessionmaker(
            conn, class_=AsyncSession, expire_on_commit=False
        )()
        
        # Begin nested transaction
        await session.begin()
        
        yield session
        
        # Rollback
        await session.rollback()
        await transaction.rollback()
        await session.close()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> TypedAsyncGenerator[AsyncClient, None]:
    """Create test HTTP client."""
    app = create_app()
    
    # Override database dependency
    from finledger.db.database import get_db
    
    async def override_get_db():
        yield db_session
    
    app.dependency_overrides[get_db] = override_get_db
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession) -> User:
    """Create a test user."""
    from finledger.core.auth.password import get_password_hash
    
    user = User(
        email="test@example.com",
        password_hash=get_password_hash("TestPass123!"),
        full_name="Test User",
        role="USER",
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession) -> User:
    """Create an admin test user."""
    from finledger.core.auth.password import get_password_hash
    
    user = User(
        email="admin@example.com",
        password_hash=get_password_hash("AdminPass123!"),
        full_name="Admin User",
        role="ADMIN",
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def test_wallet(db_session: AsyncSession, test_user: User) -> Wallet:
    """Create a test wallet."""
    wallet = Wallet(
        user_id=test_user.id,
        currency="USD",
        name="Test Wallet",
        status="ACTIVE",
    )
    db_session.add(wallet)
    await db_session.flush()
    await db_session.refresh(wallet)
    return wallet


@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient, test_user: User) -> dict:
    """Get authentication headers for test user."""
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": test_user.email, "password": "TestPass123!"},
    )
    assert response.status_code == 200
    data = response.json()
    return {"Authorization": f"Bearer {data['access_token']}"}


@pytest_asyncio.fixture
async def admin_headers(client: AsyncClient, admin_user: User) -> dict:
    """Get authentication headers for admin user."""
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": admin_user.email, "password": "AdminPass123!"},
    )
    assert response.status_code == 200
    data = response.json()
    return {"Authorization": f"Bearer {data['access_token']}"}


@pytest_asyncio.fixture
async def idempotency_key() -> str:
    """Generate a unique idempotency key for tests."""
    return str(uuid4())