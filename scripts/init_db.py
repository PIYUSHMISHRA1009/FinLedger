#!/usr/bin/env python
"""
Database initialization script.

Creates database, runs migrations, and seeds initial data.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from alembic.config import Config
from alembic import command
from finledger.api.config.settings import get_settings
from finledger.db.database import db_manager, Base


async def create_database() -> None:
    """Create database if it doesn't exist."""
    settings = get_settings()
    
    # Parse database URL to get database name
    # postgresql+asyncpg://user:pass@host:port/dbname
    db_url = settings.DATABASE_URL
    if "postgresql" in db_url:
        # Connect to postgres database to create our database
        import asyncpg
        
        # Extract connection params
        # postgresql+asyncpg://finledger:dev_password@localhost:5432/finledger
        parts = db_url.replace("postgresql+asyncpg://", "").split("/")
        auth_host = parts[0]  # finledger:dev_password@localhost:5432
        db_name = parts[1] if len(parts) > 1 else "finledger"
        
        auth_parts = auth_host.split("@")
        credentials = auth_parts[0].split(":")  # finledger:dev_password
        host_port = auth_parts[1].split(":")  # localhost:5432
        
        user = credentials[0]
        password = credentials[1] if len(credentials) > 1 else ""
        host = host_port[0]
        port = int(host_port[1]) if len(host_port) > 1 else 5432
        
        try:
            conn = await asyncpg.connect(
                user=user,
                password=password,
                host=host,
                port=port,
                database="postgres",
            )
            # Check if database exists
            exists = await conn.fetchval(
                "SELECT 1 FROM pg_database WHERE datname = $1", db_name
            )
            if not exists:
                await conn.execute(f'CREATE DATABASE "{db_name}"')
                print(f"Created database: {db_name}")
            else:
                print(f"Database already exists: {db_name}")
            await conn.close()
        except Exception as e:
            print(f"Could not create database (may already exist): {e}")


async def run_migrations() -> None:
    """Run Alembic migrations."""
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")
    print("Migrations completed successfully")


async def init_db() -> None:
    """Initialize database: create, migrate, and verify."""
    print("Initializing FinLedger database...")
    
    # Create database
    await create_database()
    
    # Initialize database manager
    db_manager.initialize()
    
    # Run migrations
    await run_migrations()
    
    # Verify tables exist
    async with db_manager.session() as session:
        from sqlalchemy import text
        result = await session.execute(text("""
            SELECT table_name FROM information_schema.tables 
            WHERE table_schema = 'public' 
            ORDER BY table_name
        """))
        tables = [row[0] for row in result]
        print(f"\nCreated tables ({len(tables)}):")
        for table in tables:
            print(f"  - {table}")
    
    await db_manager.close()
    print("\nDatabase initialization complete!")


if __name__ == "__main__":
    asyncio.run(init_db())