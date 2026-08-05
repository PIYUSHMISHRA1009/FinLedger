#!/usr/bin/env python
"""
Seed data script for development/testing.

Adds test users, wallets, and sample transactions.
"""

import asyncio
import sys
from decimal import Decimal
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from finledger.db.database import db_manager
from finledger.db.models import (
    User, Wallet, LedgerAccount, LedgerTransaction, LedgerEntry,
    AccountBalance, Transaction, FraudEvent, FraudRule
)
from finledger.core.auth.password import get_password_hash
from sqlalchemy import select, func


async def seed_users() -> list:
    """Create test users."""
    async with db_manager.session() as session:
        # Check if users already exist
        existing = await session.execute(select(User).limit(1))
        if existing.scalar_one_or_none():
            print("Users already exist, skipping...")
            return []

        users = [
            User(
                email="admin@finledger.io",
                password_hash=get_password_hash("AdminPass123!"),
                full_name="Admin User",
                role="ADMIN",
                is_active=True,
                is_verified=True,
            ),
            User(
                email="compliance@finledger.io",
                password_hash=get_password_hash("CompliancePass123!"),
                full_name="Compliance Officer",
                role="COMPLIANCE",
                is_active=True,
                is_verified=True,
            ),
            User(
                email="alice@example.com",
                password_hash=get_password_hash("AlicePass123!"),
                full_name="Alice Johnson",
                role="USER",
                is_active=True,
                is_verified=True,
            ),
            User(
                email="bob@example.com",
                password_hash=get_password_hash("BobPass123!"),
                full_name="Bob Smith",
                role="USER",
                is_active=True,
                is_verified=True,
            ),
            User(
                email="charlie@example.com",
                password_hash=get_password_hash("CharliePass123!"),
                full_name="Charlie Brown",
                role="USER",
                is_active=True,
                is_verified=True,
            ),
        ]

        session.add_all(users)
        await session.commit()
        
        for user in users:
            await session.refresh(user)
        
        print(f"Created {len(users)} test users")
        return users


async def seed_wallets(users: list) -> list:
    """Create wallets for users."""
    async with db_manager.session() as session:
        # Check if wallets already exist
        existing = await session.execute(select(Wallet).limit(1))
        if existing.scalar_one_or_none():
            print("Wallets already exist, skipping...")
            return []

        alice = next(u for u in users if u.email == "alice@example.com")
        bob = next(u for u in users if u.email == "bob@example.com")
        charlie = next(u for u in users if u.email == "charlie@example.com")

        wallets = [
            Wallet(user_id=alice.id, currency="USD", name="Primary USD", status="ACTIVE"),
            Wallet(user_id=alice.id, currency="EUR", name="Euro Wallet", status="ACTIVE"),
            Wallet(user_id=bob.id, currency="USD", name="Main Wallet", status="ACTIVE"),
            Wallet(user_id=bob.id, currency="GBP", name="GBP Wallet", status="ACTIVE"),
            Wallet(user_id=charlie.id, currency="USD", name="Savings", status="ACTIVE"),
        ]

        session.add_all(wallets)
        await session.commit()
        
        for wallet in wallets:
            await session.refresh(wallet)
        
        print(f"Created {len(wallets)} test wallets")
        return wallets


async def seed_balances(wallets: list) -> None:
    """Create initial account balances for wallets."""
    async with db_manager.session() as session:
        # Get liability accounts for each currency
        liability_accounts = {}
        for currency in ["USD", "EUR", "GBP"]:
            result = await session.execute(
                select(LedgerAccount).where(
                    LedgerAccount.code == f"201{currency[-1]}"  # 2010, 2011, 2012
                )
            )
            account = result.scalar_one_or_none()
            if account:
                liability_accounts[currency] = account

        # Create balances for each wallet
        balances = []
        for wallet in wallets:
            if wallet.currency in liability_accounts:
                account = liability_accounts[wallet.currency]
                
                # Set initial balances (simulating deposits)
                initial_amount = Decimal("1000.00") if wallet.name == "Primary USD" else \
                               Decimal("500.00") if wallet.name == "Main Wallet" else \
                               Decimal("250.00")
                
                balance = AccountBalance(
                    ledger_account_id=account.id,
                    wallet_id=wallet.id,
                    posted_balance=-initial_amount,  # Negative for liability
                    pending_balance=-initial_amount,
                    available_balance=-initial_amount,
                )
                balances.append(balance)

        if balances:
            session.add_all(balances)
            await session.commit()
            print(f"Created {len(balances)} initial account balances")


async def seed_transactions(wallets: list) -> None:
    """Create sample transactions between wallets."""
    async with db_manager.session() as session:
        existing = await session.execute(select(Transaction).limit(1))
        if existing.scalar_one_or_none():
            print("Transactions already exist, skipping...")
            return

        alice_usd = next(w for w in wallets if w.user_id == next(u for u in users if u.email == "alice@example.com").id and w.currency == "USD")
        bob_usd = next(w for w in wallets if w.user_id == next(u for u in users if u.email == "bob@example.com").id and w.currency == "USD")
        charlie_usd = next(w for w in wallets if w.user_id == next(u for u in users if u.email == "charlie@example.com").id and w.currency == "USD")

        # Get liability account for USD
        liability_account = await session.execute(
            select(LedgerAccount).where(LedgerAccount.code == "2010")
        )
        liability_account = liability_account.scalar_one()

        # Get asset account for USD
        asset_account = await session.execute(
            select(LedgerAccount).where(LedgerAccount.code == "1010")
        )
        asset_account = asset_account.scalar_one()

        transactions = [
            Transaction(
                source_wallet_id=alice_usd.id,
                destination_wallet_id=bob_usd.id,
                type="TRANSFER_OUT",
                status="COMPLETED",
                amount=Decimal("50.00"),
                currency="USD",
                description="Payment to Bob",
                idempotency_key="seed-txn-001",
                completed_at=func.now(),
            ),
            Transaction(
                source_wallet_id=bob_usd.id,
                destination_wallet_id=charlie_usd.id,
                type="TRANSFER_OUT",
                status="COMPLETED",
                amount=Decimal("25.00"),
                currency="USD",
                description="Payment to Charlie",
                idempotency_key="seed-txn-002",
                completed_at=func.now(),
            ),
            Transaction(
                source_wallet_id=alice_usd.id,
                destination_wallet_id=None,
                type="WITHDRAWAL",
                status="COMPLETED",
                amount=Decimal("100.00"),
                currency="USD",
                description="ATM withdrawal",
                idempotency_key="seed-txn-003",
                completed_at=func.now(),
            ),
        ]

        session.add_all(transactions)
        await session.commit()
        
        for txn in transactions:
            await session.refresh(txn)
        
        print(f"Created {len(transactions)} sample transactions")


async def main():
    """Run all seed functions."""
    print("Seeding FinLedger database...")
    
    db_manager.initialize()
    
    users = await seed_users()
    wallets = await seed_wallets(users)
    await seed_balances(wallets)
    await seed_transactions(wallets)
    
    await db_manager.close()
    print("Seeding complete!")


if __name__ == "__main__":
    # Import users at module level for seed_transactions
    from finledger.db.models import User
    users = []
    asyncio.run(main())