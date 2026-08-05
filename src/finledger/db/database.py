"""
FinLedger Database Configuration

Async SQLAlchemy setup with connection pooling and session management.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from sqlalchemy import event, pool
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from finledger.api.config.settings import get_settings


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""
    pass


class DatabaseManager:
    """Manages database engine and session lifecycle."""

    def __init__(self):
        self._engine: Optional[AsyncEngine] = None
        self._session_factory: Optional[async_sessionmaker[AsyncSession]] = None

    def initialize(self) -> None:
        """Initialize database engine and session factory."""
        settings = get_settings()

        self._engine = create_async_engine(
            settings.DATABASE_URL,
            pool_size=settings.DATABASE_POOL_SIZE,
            max_overflow=settings.DATABASE_MAX_OVERFLOW,
            pool_timeout=settings.DATABASE_POOL_TIMEOUT,
            pool_pre_ping=True,
            pool_recycle=3600,
            echo=settings.DATABASE_ECHO,
            # Use NullPool for testing to avoid connection issues
            poolclass=pool.NullPool if settings.is_test else pool.AsyncAdaptedQueuePool,
        )

        self._session_factory = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )

    @property
    def engine(self) -> AsyncEngine:
        if self._engine is None:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        return self._engine

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        if self._session_factory is None:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        return self._session_factory

    async def close(self) -> None:
        """Close database connections."""
        if self._engine:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Get a database session."""
        async with self.session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    async def create_tables(self) -> None:
        """Create all tables (use with caution in production)."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def drop_tables(self) -> None:
        """Drop all tables (use with caution)."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)


# Global database manager instance
db_manager = DatabaseManager()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for database session."""
    async with db_manager.session() as session:
        yield session


# Database event listeners for audit logging
@event.listens_for(Base.metadata, "before_create")
def receive_before_create(target, connection, **kw):
    """Enable UUID extension before creating tables."""
    if target.bind.dialect.name == "postgresql":
        connection.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\"")
        connection.execute("CREATE EXTENSION IF NOT EXISTS \"pgcrypto\"")
        connection.execute("CREATE EXTENSION IF NOT EXISTS \"btree_gin\"")