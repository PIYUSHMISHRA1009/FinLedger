"""
Initial migration - Create all FinLedger tables with seed data.

Revision ID: 001_initial
Revises: 
Create Date: 2024-01-15 10:00:00.000000
"""

from typing import Sequence, Union
from decimal import Decimal

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, INET
import sqlalchemy.dialects.postgresql as postgresql

# revision identifiers, used by Alembic.
revision: str = '001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create enum types
    user_role = postgresql.ENUM(
        'USER', 'ADMIN', 'COMPLIANCE', 'SYSTEM',
        name='user_role', create_type=True
    )
    user_role.create(op.get_bind(), checkfirst=True)

    wallet_status = postgresql.ENUM(
        'ACTIVE', 'FROZEN', 'CLOSED', 'PENDING_VERIFICATION',
        name='wallet_status', create_type=True
    )
    wallet_status.create(op.get_bind(), checkfirst=True)

    transaction_type = postgresql.ENUM(
        'DEPOSIT', 'WITHDRAWAL', 'TRANSFER_IN', 'TRANSFER_OUT',
        'FEE', 'REVERSAL', 'ADJUSTMENT',
        name='transaction_type', create_type=True
    )
    transaction_type.create(op.get_bind(), checkfirst=True)

    transaction_status = postgresql.ENUM(
        'PENDING', 'PROCESSING', 'COMPLETED', 'FAILED',
        'BLOCKED', 'REVERSED', 'CANCELLED',
        name='transaction_status', create_type=True
    )
    transaction_status.create(op.get_bind(), checkfirst=True)

    account_type = postgresql.ENUM(
        'ASSET', 'LIABILITY', 'EQUITY', 'REVENUE', 'EXPENSE',
        name='account_type', create_type=True
    )
    account_type.create(op.get_bind(), checkfirst=True)

    account_normality = postgresql.ENUM(
        'DEBIT', 'CREDIT',
        name='account_normality', create_type=True
    )
    account_normality.create(op.get_bind(), checkfirst=True)

    ledger_entry_type = postgresql.ENUM(
        'DEBIT', 'CREDIT',
        name='ledger_entry_type', create_type=True
    )
    ledger_entry_type.create(op.get_bind(), checkfirst=True)

    ledger_txn_status = postgresql.ENUM(
        'DRAFT', 'POSTED', 'VOIDED',
        name='ledger_txn_status', create_type=True
    )
    ledger_txn_status.create(op.get_bind(), checkfirst=True)

    fraud_rule_type = postgresql.ENUM(
        'VELOCITY', 'AMOUNT_THRESHOLD', 'COUNTERPARTY_FREQUENCY',
        'SUSPICIOUS_PATTERN', 'GEO_VELOCITY', 'ML_SCORE',
        name='fraud_rule_type', create_type=True
    )
    fraud_rule_type.create(op.get_bind(), checkfirst=True)

    fraud_risk_level = postgresql.ENUM(
        'LOW', 'MEDIUM', 'HIGH', 'CRITICAL',
        name='fraud_risk_level', create_type=True
    )
    fraud_risk_level.create(op.get_bind(), checkfirst=True)

    fraud_event_status = postgresql.ENUM(
        'PENDING_REVIEW', 'APPROVED', 'BLOCKED', 'FALSE_POSITIVE', 'ESCALATED',
        name='fraud_event_status', create_type=True
    )
    fraud_event_status.create(op.get_bind(), checkfirst=True)

    # Create users table
    op.create_table(
        'users',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('email', sa.String(255), nullable=False, unique=True),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('full_name', sa.String(255), nullable=False),
        sa.Column('role', user_role, nullable=False, server_default='USER'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('is_verified', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('email_verification_token', sa.String(255), nullable=True),
        sa.Column('email_verification_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('password_reset_token', sa.String(255), nullable=True),
        sa.Column('password_reset_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('failed_login_attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('idx_users_email', 'users', ['email'])
    op.create_index('idx_users_role', 'users', ['role'])
    op.create_index('idx_users_is_active', 'users', ['is_active'], postgresql_where=sa.text('is_active = true'))

    # Create refresh_tokens table
    op.create_table(
        'refresh_tokens',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('token_hash', sa.String(255), nullable=False, unique=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_reason', sa.String(255), nullable=True),
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.Column('ip_address', INET(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('idx_refresh_tokens_user_id', 'refresh_tokens', ['user_id'])
    op.create_index('idx_refresh_tokens_expires_at', 'refresh_tokens', ['expires_at'], postgresql_where=sa.text('revoked = false'))
    op.create_index('idx_refresh_tokens_token_hash', 'refresh_tokens', ['token_hash'])
    op.create_index('idx_refresh_tokens_user_expires', 'refresh_tokens', ['user_id', 'expires_at'], postgresql_where=sa.text('revoked = false'))

    # Create wallets table
    op.create_table(
        'wallets',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('status', wallet_status, nullable=False, server_default='PENDING_VERIFICATION'),
        sa.Column('settings', JSONB(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("LENGTH(currency) = 3", name='chk_currency_length'),
    )
    op.create_index('idx_wallets_user_id', 'wallets', ['user_id'])
    op.create_index('idx_wallets_currency', 'wallets', ['currency'])
    op.create_index('idx_wallets_status', 'wallets', ['status'])
    op.create_index('idx_wallets_user_currency_name', 'wallets', ['user_id', 'currency', 'name'], 
                    postgresql_where=sa.text("status IN ('ACTIVE', 'PENDING_VERIFICATION')"), unique=True)

    # Create ledger_accounts table
    op.create_table(
        'ledger_accounts',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('code', sa.String(50), nullable=False, unique=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('account_type', account_type, nullable=False),
        sa.Column('normality', account_normality, nullable=False),
        sa.Column('parent_account_id', UUID(as_uuid=True), sa.ForeignKey('ledger_accounts.id', ondelete='SET NULL'), nullable=True),
        sa.Column('currency', sa.String(3), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('is_system_account', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("currency IS NULL OR LENGTH(currency) = 3", name='chk_currency_length'),
    )
    op.create_index('idx_ledger_accounts_code', 'ledger_accounts', ['code'])
    op.create_index('idx_ledger_accounts_parent', 'ledger_accounts', ['parent_account_id'])
    op.create_index('idx_ledger_accounts_type', 'ledger_accounts', ['account_type'])
    op.create_index('idx_ledger_accounts_active', 'ledger_accounts', ['is_active'], postgresql_where=sa.text('is_active = true'))

    # Create ledger_transactions table
    op.create_table(
        'ledger_transactions',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('reference', sa.String(100), nullable=False, unique=True),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('status', ledger_txn_status, nullable=False, server_default='DRAFT'),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('posted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('voided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('voided_reason', sa.Text(), nullable=True),
        sa.Column('metadata', JSONB(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('idx_ledger_transactions_reference', 'ledger_transactions', ['reference'])
    op.create_index('idx_ledger_transactions_status', 'ledger_transactions', ['status'])
    op.create_index('idx_ledger_transactions_posted_at', 'ledger_transactions', ['posted_at'], 
                    postgresql_where=sa.text("status = 'POSTED'"))

    # Create ledger_entries table
    op.create_table(
        'ledger_entries',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('ledger_transaction_id', UUID(as_uuid=True), sa.ForeignKey('ledger_transactions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('ledger_account_id', UUID(as_uuid=True), sa.ForeignKey('ledger_accounts.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('wallet_id', UUID(as_uuid=True), sa.ForeignKey('wallets.id', ondelete='CASCADE'), nullable=True),
        sa.Column('entry_type', ledger_entry_type, nullable=False),
        sa.Column('amount', sa.Numeric(19, 4), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('metadata', JSONB(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint('amount > 0', name='chk_amount_positive'),
    )
    op.create_index('idx_ledger_entries_txn_id', 'ledger_entries', ['ledger_transaction_id'])
    op.create_index('idx_ledger_entries_account_id', 'ledger_entries', ['ledger_account_id'])
    op.create_index('idx_ledger_entries_type', 'ledger_entries', ['entry_type'])
    op.create_index('idx_ledger_entries_txn_account', 'ledger_entries', ['ledger_transaction_id', 'ledger_account_id'],
                    postgresql_include=['entry_type', 'amount'])

    # Create transactions table
    op.create_table(
        'transactions',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('source_wallet_id', UUID(as_uuid=True), sa.ForeignKey('wallets.id', ondelete='SET NULL'), nullable=True),
        sa.Column('destination_wallet_id', UUID(as_uuid=True), sa.ForeignKey('wallets.id', ondelete='SET NULL'), nullable=True),
        sa.Column('ledger_transaction_id', UUID(as_uuid=True), sa.ForeignKey('ledger_transactions.id', ondelete='SET NULL'), nullable=True),
        sa.Column('type', transaction_type, nullable=False),
        sa.Column('status', transaction_status, nullable=False, server_default='PENDING'),
        sa.Column('amount', sa.Numeric(19, 4), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('idempotency_key', sa.String(255), nullable=False, unique=True),
        sa.Column('metadata', JSONB(), nullable=False, server_default='{}'),
        sa.Column('failure_reason', sa.Text(), nullable=True),
        sa.Column('failure_code', sa.String(50), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_retries', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('failed_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint('amount > 0', name='chk_amount_positive'),
        sa.CheckConstraint("LENGTH(currency) = 3", name='chk_currency_length'),
        sa.CheckConstraint(
            "source_wallet_id IS NULL OR destination_wallet_id IS NULL OR source_wallet_id != destination_wallet_id",
            name='chk_wallets_different',
        ),
    )
    op.create_index('idx_transactions_source_wallet', 'transactions', ['source_wallet_id'])
    op.create_index('idx_transactions_dest_wallet', 'transactions', ['destination_wallet_id'])
    op.create_index('idx_transactions_status', 'transactions', ['status'])
    op.create_index('idx_transactions_type', 'transactions', ['type'])
    op.create_index('idx_transactions_idempotency', 'transactions', ['idempotency_key'])
    op.create_index('idx_transactions_created_at', 'transactions', ['created_at'], postgresql_using='btree', postgresql_ops={'created_at': 'DESC'})
    op.create_index('idx_transactions_ledger_txn', 'transactions', ['ledger_transaction_id'])
    op.create_index('idx_transactions_wallet_created', 'transactions', ['source_wallet_id', 'created_at'],
                    postgresql_using='btree', postgresql_ops={'created_at': 'DESC'},
                    postgresql_include=['type', 'amount', 'status', 'description'])

    # Create account_balances table
    op.create_table(
        'account_balances',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('ledger_account_id', UUID(as_uuid=True), sa.ForeignKey('ledger_accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('wallet_id', UUID(as_uuid=True), sa.ForeignKey('wallets.id', ondelete='CASCADE'), nullable=True),
        sa.Column('posted_balance', sa.Numeric(19, 4), nullable=False, server_default='0'),
        sa.Column('pending_balance', sa.Numeric(19, 4), nullable=False, server_default='0'),
        sa.Column('available_balance', sa.Numeric(19, 4), nullable=False, server_default='0'),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('last_transaction_id', UUID(as_uuid=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('ledger_account_id', 'wallet_id', name='uq_account_wallet'),
    )
    op.create_index('idx_account_balances_account', 'account_balances', ['ledger_account_id'])
    op.create_index('idx_account_balances_wallet', 'account_balances', ['wallet_id'])

    # Create fraud_rules table
    op.create_table(
        'fraud_rules',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('code', sa.String(50), nullable=False, unique=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('rule_type', fraud_rule_type, nullable=False),
        sa.Column('weight', sa.Numeric(4, 3), nullable=False, server_default='0.100'),
        sa.Column('parameters', JSONB(), nullable=False, server_default='{}'),
        sa.Column('active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='100'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('idx_fraud_rules_active', 'fraud_rules', ['active'], postgresql_where=sa.text('active = true'))
    op.create_index('idx_fraud_rules_priority', 'fraud_rules', ['priority'])

    # Create fraud_events table
    op.create_table(
        'fraud_events',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('transaction_id', UUID(as_uuid=True), sa.ForeignKey('transactions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('wallet_id', UUID(as_uuid=True), sa.ForeignKey('wallets.id', ondelete='CASCADE'), nullable=False),
        sa.Column('risk_score', sa.Numeric(4, 3), nullable=False),
        sa.Column('risk_level', fraud_risk_level, nullable=False),
        sa.Column('triggered_rules', JSONB(), nullable=False, server_default='[]'),
        sa.Column('status', fraud_event_status, nullable=False, server_default='PENDING_REVIEW'),
        sa.Column('reviewer_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('review_notes', sa.Text(), nullable=True),
        sa.Column('auto_blocked', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('ml_score', sa.Numeric(4, 3), nullable=True),
        sa.Column('ml_model_version', sa.String(50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('idx_fraud_events_transaction', 'fraud_events', ['transaction_id'])
    op.create_index('idx_fraud_events_user', 'fraud_events', ['user_id'])
    op.create_index('idx_fraud_events_wallet', 'fraud_events', ['wallet_id'])
    op.create_index('idx_fraud_events_risk_level', 'fraud_events', ['risk_level'])
    op.create_index('idx_fraud_events_status', 'fraud_events', ['status'])
    op.create_index('idx_fraud_events_created_at', 'fraud_events', ['created_at'], postgresql_using='btree', postgresql_ops={'created_at': 'DESC'})
    op.create_index('idx_fraud_events_review_queue', 'fraud_events', ['risk_level', 'status', 'created_at'],
                    postgresql_where=sa.text("status = 'PENDING_REVIEW'"), 
                    postgresql_using='btree', postgresql_ops={'created_at': 'DESC'})

    # Create idempotency_keys table
    op.create_table(
        'idempotency_keys',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('key', sa.String(255), nullable=False, unique=True),
        sa.Column('transaction_id', UUID(as_uuid=True), sa.ForeignKey('transactions.id', ondelete='SET NULL'), nullable=True),
        sa.Column('request_method', sa.String(10), nullable=False),
        sa.Column('request_path', sa.String(500), nullable=False),
        sa.Column('request_body', JSONB(), nullable=True),
        sa.Column('response_status', sa.Integer(), nullable=True),
        sa.Column('response_body', JSONB(), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('idx_idempotency_keys_expires', 'idempotency_keys', ['expires_at'])
    op.create_index('idx_idempotency_keys_txn', 'idempotency_keys', ['transaction_id'])

    # Create audit_logs table
    op.create_table(
        'audit_logs',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('action', sa.String(100), nullable=False),
        sa.Column('resource_type', sa.String(100), nullable=False),
        sa.Column('resource_id', UUID(as_uuid=True), nullable=True),
        sa.Column('old_values', JSONB(), nullable=True),
        sa.Column('new_values', JSONB(), nullable=True),
        sa.Column('ip_address', INET(), nullable=True),
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.Column('request_id', sa.String(100), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('idx_audit_logs_user', 'audit_logs', ['user_id'])
    op.create_index('idx_audit_logs_resource', 'audit_logs', ['resource_type', 'resource_id', 'created_at'])
    op.create_index('idx_audit_logs_action', 'audit_logs', ['action'])
    op.create_index('idx_audit_logs_created_at', 'audit_logs', ['created_at'], postgresql_using='btree', postgresql_ops={'created_at': 'DESC'})
    op.create_index('idx_audit_logs_request_id', 'audit_logs', ['request_id'])

    # Create updated_at trigger function
    op.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Apply updated_at triggers
    for table in ['users', 'wallets', 'ledger_accounts', 'ledger_transactions', 
                  'transactions', 'fraud_rules', 'fraud_events']:
        op.execute(f"""
            CREATE TRIGGER update_{table}_updated_at 
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
        """)

    # Ledger balance validation trigger
    op.execute("""
        CREATE OR REPLACE FUNCTION validate_ledger_transaction_balance()
        RETURNS TRIGGER AS $$
        DECLARE
            debit_total NUMERIC(19, 4);
            credit_total NUMERIC(19, 4);
        BEGIN
            IF NEW.status = 'POSTED' AND (OLD.status IS NULL OR OLD.status != 'POSTED') THEN
                SELECT COALESCE(SUM(amount), 0) INTO debit_total
                FROM ledger_entries
                WHERE ledger_transaction_id = NEW.id AND entry_type = 'DEBIT';
                
                SELECT COALESCE(SUM(amount), 0) INTO credit_total
                FROM ledger_entries
                WHERE ledger_transaction_id = NEW.id AND entry_type = 'CREDIT';
                
                IF debit_total != credit_total THEN
                    RAISE EXCEPTION 'Ledger transaction % not balanced: debits=%, credits=%', 
                        NEW.id, debit_total, credit_total;
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER validate_ledger_balance 
        BEFORE UPDATE ON ledger_transactions
        FOR EACH ROW EXECUTE FUNCTION validate_ledger_transaction_balance();
    """)

    # ============================================================
    # SEED DATA: Chart of Accounts (Standard Financial Services)
    # ============================================================
    
    # Assets
    op.bulk_insert(
        sa.table(
            'ledger_accounts',
            sa.Column('code', sa.String(50)),
            sa.Column('name', sa.String(255)),
            sa.Column('account_type', account_type),
            sa.Column('normality', account_normality),
            sa.Column('is_system_account', sa.Boolean()),
            sa.Column('description', sa.Text()),
            sa.Column('is_active', sa.Boolean()),
        ),
        [
            {'code': '1000', 'name': 'Cash & Cash Equivalents', 'account_type': 'ASSET', 'normality': 'DEBIT', 
             'is_system_account': True, 'description': 'Physical and digital cash', 'is_active': True},
            {'code': '1010', 'name': 'Customer Wallets - USD', 'account_type': 'ASSET', 'normality': 'DEBIT', 
             'is_system_account': True, 'description': 'End-user USD wallet balances', 'is_active': True},
            {'code': '1011', 'name': 'Customer Wallets - EUR', 'account_type': 'ASSET', 'normality': 'DEBIT', 
             'is_system_account': True, 'description': 'End-user EUR wallet balances', 'is_active': True},
            {'code': '1012', 'name': 'Customer Wallets - GBP', 'account_type': 'ASSET', 'normality': 'DEBIT', 
             'is_system_account': True, 'description': 'End-user GBP wallet balances', 'is_active': True},
            {'code': '1020', 'name': 'Operating Bank Accounts', 'account_type': 'ASSET', 'normality': 'DEBIT', 
             'is_system_account': True, 'description': 'Company operational bank accounts', 'is_active': True},
            {'code': '1030', 'name': 'Settlement Accounts', 'account_type': 'ASSET', 'normality': 'DEBIT', 
             'is_system_account': True, 'description': 'Pending settlement with payment rails', 'is_active': True},
            {'code': '1040', 'name': 'Receivables', 'account_type': 'ASSET', 'normality': 'DEBIT', 
             'is_system_account': True, 'description': 'Amounts owed to the platform', 'is_active': True},
            {'code': '1050', 'name': 'Prepaid Expenses', 'account_type': 'ASSET', 'normality': 'DEBIT', 
             'is_system_account': True, 'description': 'Prepaid vendor expenses', 'is_active': True},
        ]
    )

    # Liabilities
    op.bulk_insert(
        sa.table(
            'ledger_accounts',
            sa.Column('code', sa.String(50)),
            sa.Column('name', sa.String(255)),
            sa.Column('account_type', account_type),
            sa.Column('normality', account_normality),
            sa.Column('is_system_account', sa.Boolean()),
            sa.Column('description', sa.Text()),
            sa.Column('is_active', sa.Boolean()),
        ),
        [
            {'code': '2000', 'name': 'Customer Liabilities', 'account_type': 'LIABILITY', 'normality': 'CREDIT', 
             'is_system_account': True, 'description': 'Funds held on behalf of customers', 'is_active': True},
            {'code': '2010', 'name': 'Customer Liabilities - USD', 'account_type': 'LIABILITY', 'normality': 'CREDIT', 
             'is_system_account': True, 'description': 'USD customer fund obligations', 'is_active': True},
            {'code': '2011', 'name': 'Customer Liabilities - EUR', 'account_type': 'LIABILITY', 'normality': 'CREDIT', 
             'is_system_account': True, 'description': 'EUR customer fund obligations', 'is_active': True},
            {'code': '2012', 'name': 'Customer Liabilities - GBP', 'account_type': 'LIABILITY', 'normality': 'CREDIT', 
             'is_system_account': True, 'description': 'GBP customer fund obligations', 'is_active': True},
            {'code': '2020', 'name': 'Accounts Payable', 'account_type': 'LIABILITY', 'normality': 'CREDIT', 
             'is_system_account': True, 'description': 'Amounts owed to vendors', 'is_active': True},
            {'code': '2030', 'name': 'Accrued Expenses', 'account_type': 'LIABILITY', 'normality': 'CREDIT', 
             'is_system_account': True, 'description': 'Expenses incurred but not paid', 'is_active': True},
            {'code': '2040', 'name': 'Deferred Revenue', 'account_type': 'LIABILITY', 'normality': 'CREDIT', 
             'is_system_account': True, 'description': 'Revenue received but not earned', 'is_active': True},
            {'code': '2050', 'name': 'Settlement Payables', 'account_type': 'LIABILITY', 'normality': 'CREDIT', 
             'is_system_account': True, 'description': 'Pending payouts to payment rails', 'is_active': True},
        ]
    )

    # Equity
    op.bulk_insert(
        sa.table(
            'ledger_accounts',
            sa.Column('code', sa.String(50)),
            sa.Column('name', sa.String(255)),
            sa.Column('account_type', account_type),
            sa.Column('normality', account_normality),
            sa.Column('is_system_account', sa.Boolean()),
            sa.Column('description', sa.Text()),
            sa.Column('is_active', sa.Boolean()),
        ),
        [
            {'code': '3000', 'name': 'Platform Equity', 'account_type': 'EQUITY', 'normality': 'CREDIT', 
             'is_system_account': True, 'description': 'Platform retained earnings', 'is_active': True},
            {'code': '3010', 'name': 'Fee Revenue', 'account_type': 'EQUITY', 'normality': 'CREDIT', 
             'is_system_account': True, 'description': 'Net fee income', 'is_active': True},
            {'code': '3020', 'name': 'Interest Income', 'account_type': 'EQUITY', 'normality': 'CREDIT', 
             'is_system_account': True, 'description': 'Net interest margin', 'is_active': True},
        ]
    )

    # Revenue
    op.bulk_insert(
        sa.table(
            'ledger_accounts',
            sa.Column('code', sa.String(50)),
            sa.Column('name', sa.String(255)),
            sa.Column('account_type', account_type),
            sa.Column('normality', account_normality),
            sa.Column('is_system_account', sa.Boolean()),
            sa.Column('description', sa.Text()),
            sa.Column('is_active', sa.Boolean()),
        ),
        [
            {'code': '4000', 'name': 'Transaction Fees', 'account_type': 'REVENUE', 'normality': 'CREDIT', 
             'is_system_account': True, 'description': 'Fees charged on transactions', 'is_active': True},
            {'code': '4010', 'name': 'Transfer Fees', 'account_type': 'REVENUE', 'normality': 'CREDIT', 
             'is_system_account': True, 'description': 'Fees on wallet-to-wallet transfers', 'is_active': True},
            {'code': '4020', 'name': 'Deposit Fees', 'account_type': 'REVENUE', 'normality': 'CREDIT', 
             'is_system_account': True, 'description': 'Fees on deposits', 'is_active': True},
            {'code': '4030', 'name': 'Withdrawal Fees', 'account_type': 'REVENUE', 'normality': 'CREDIT', 
             'is_system_account': True, 'description': 'Fees on withdrawals', 'is_active': True},
            {'code': '4040', 'name': 'FX Spread Revenue', 'account_type': 'REVENUE', 'normality': 'CREDIT', 
             'is_system_account': True, 'description': 'Revenue from FX markups', 'is_active': True},
            {'code': '4050', 'name': 'Interest Revenue', 'account_type': 'REVENUE', 'normality': 'CREDIT', 
             'is_system_account': True, 'description': 'Interest earned on float', 'is_active': True},
        ]
    )

    # Expenses
    op.bulk_insert(
        sa.table(
            'ledger_accounts',
            sa.Column('code', sa.String(50)),
            sa.Column('name', sa.String(255)),
            sa.Column('account_type', account_type),
            sa.Column('normality', account_normality),
            sa.Column('is_system_account', sa.Boolean()),
            sa.Column('description', sa.Text()),
            sa.Column('is_active', sa.Boolean()),
        ),
        [
            {'code': '5000', 'name': 'Payment Processing Fees', 'account_type': 'EXPENSE', 'normality': 'DEBIT', 
             'is_system_account': True, 'description': 'Fees paid to payment processors', 'is_active': True},
            {'code': '5010', 'name': 'Bank Fees', 'account_type': 'EXPENSE', 'normality': 'DEBIT', 
             'is_system_account': True, 'description': 'Bank service charges', 'is_active': True},
            {'code': '5020', 'name': 'Network Fees', 'account_type': 'EXPENSE', 'normality': 'DEBIT', 
             'is_system_account': True, 'description': 'Card network / rail fees', 'is_active': True},
            {'code': '5030', 'name': 'Fraud Losses', 'account_type': 'EXPENSE', 'normality': 'DEBIT', 
             'is_system_account': True, 'description': 'Net fraud write-offs', 'is_active': True},
            {'code': '5040', 'name': 'Operational Expenses', 'account_type': 'EXPENSE', 'normality': 'DEBIT', 
             'is_system_account': True, 'description': 'General operational costs', 'is_active': True},
        ]
    )

    # ============================================================
    # SEED DATA: Fraud Rules
    # ============================================================
    
    op.bulk_insert(
        sa.table(
            'fraud_rules',
            sa.Column('code', sa.String(50)),
            sa.Column('name', sa.String(255)),
            sa.Column('description', sa.Text()),
            sa.Column('rule_type', fraud_rule_type),
            sa.Column('weight', sa.Numeric(4, 3)),
            sa.Column('parameters', JSONB()),
            sa.Column('active', sa.Boolean()),
            sa.Column('priority', sa.Integer()),
        ),
        [
            {
                'code': 'VELOCITY_10PM',
                'name': 'High Velocity - 10 Transactions/Minute',
                'description': 'Triggers when a user exceeds 10 transactions in a rolling 1-minute window',
                'rule_type': 'VELOCITY',
                'weight': Decimal('0.300'),
                'parameters': {"window_seconds": 60, "threshold": 10, "scope": "user"},
                'active': True,
                'priority': 10,
            },
            {
                'code': 'VELOCITY_50PH',
                'name': 'High Velocity - 50 Transactions/Hour',
                'description': 'Triggers when a user exceeds 50 transactions in a rolling 1-hour window',
                'rule_type': 'VELOCITY',
                'weight': Decimal('0.250'),
                'parameters': {"window_seconds": 3600, "threshold": 50, "scope": "user"},
                'active': True,
                'priority': 20,
            },
            {
                'code': 'VELOCITY_WALLET_20PM',
                'name': 'Wallet Velocity - 20 Transactions/Minute',
                'description': 'Triggers when a wallet exceeds 20 transactions in a rolling 1-minute window',
                'rule_type': 'VELOCITY',
                'weight': Decimal('0.200'),
                'parameters': {"window_seconds": 60, "threshold": 20, "scope": "wallet"},
                'active': True,
                'priority': 30,
            },
            {
                'code': 'LARGE_TXN_P95',
                'name': 'Large Transaction - Above 95th Percentile',
                'description': 'Triggers when transaction amount exceeds the 95th percentile for the user',
                'rule_type': 'AMOUNT_THRESHOLD',
                'weight': Decimal('0.350'),
                'parameters': {"percentile": 95, "lookback_days": 90, "min_transactions": 10},
                'active': True,
                'priority': 40,
            },
            {
                'code': 'LARGE_TXN_ABS_10K',
                'name': 'Large Transaction - Absolute > $10,000',
                'description': 'Triggers on any single transaction exceeding $10,000 (or currency equivalent)',
                'rule_type': 'AMOUNT_THRESHOLD',
                'weight': Decimal('0.400'),
                'parameters': {"threshold_usd": 10000},
                'active': True,
                'priority': 50,
            },
            {
                'code': 'FREQUENT_COUNTERPARTY',
                'name': 'Frequent Counterparty - >5 Transfers/Day',
                'description': 'Triggers when >5 transfers to the same counterparty in 24 hours',
                'rule_type': 'COUNTERPARTY_FREQUENCY',
                'weight': Decimal('0.200'),
                'parameters': {"window_hours": 24, "threshold": 5},
                'active': True,
                'priority': 60,
            },
            {
                'code': 'ROUND_NUMBER',
                'name': 'Suspicious Round Number Amount',
                'description': 'Triggers on suspiciously round amounts (e.g., $1000, $5000, $10000)',
                'rule_type': 'SUSPICIOUS_PATTERN',
                'weight': Decimal('0.150'),
                'parameters': {"round_thresholds": [100, 500, 1000, 5000, 10000], "tolerance": 0.01},
                'active': True,
                'priority': 70,
            },
            {
                'code': 'JUST_UNDER_LIMIT',
                'name': 'Just Under Reporting Limit',
                'description': 'Triggers on amounts just under common reporting thresholds (e.g., $9,999)',
                'rule_type': 'SUSPICIOUS_PATTERN',
                'weight': Decimal('0.250'),
                'parameters': {"thresholds": [9999, 4999, 2999, 999], "tolerance": 10},
                'active': True,
                'priority': 80,
            },
            {
                'code': 'GEO_VELOCITY',
                'name': 'Impossible Travel - Geo Velocity',
                'description': 'Triggers when transactions from geographically distant locations occur within impossible travel time',
                'rule_type': 'GEO_VELOCITY',
                'weight': Decimal('0.300'),
                'parameters': {"max_speed_kmh": 900, "min_distance_km": 500},
                'active': True,
                'priority': 90,
            },
            {
                'code': 'NEW_DEVICE',
                'name': 'New Device / IP',
                'description': 'Triggers on first transaction from a new device fingerprint or IP subnet',
                'rule_type': 'SUSPICIOUS_PATTERN',
                'weight': Decimal('0.100'),
                'parameters': {"lookback_days": 30},
                'active': True,
                'priority': 100,
            },
        ]
    )


def downgrade() -> None:
    # Drop triggers
    for table in ['users', 'wallets', 'ledger_accounts', 'ledger_transactions', 
                  'transactions', 'fraud_rules', 'fraud_events']:
        op.execute(f"DROP TRIGGER IF EXISTS update_{table}_updated_at ON {table};")
    op.execute("DROP TRIGGER IF EXISTS validate_ledger_balance ON ledger_transactions;")
    op.execute("DROP FUNCTION IF EXISTS update_updated_at_column();")
    op.execute("DROP FUNCTION IF EXISTS validate_ledger_transaction_balance();")

    # Drop tables in reverse order
    op.drop_table('audit_logs')
    op.drop_table('idempotency_keys')
    op.drop_table('fraud_events')
    op.drop_table('fraud_rules')
    op.drop_table('account_balances')
    op.drop_table('transactions')
    op.drop_table('ledger_entries')
    op.drop_table('ledger_transactions')
    op.drop_table('ledger_accounts')
    op.drop_table('wallets')
    op.drop_table('refresh_tokens')
    op.drop_table('users')

    # Drop enum types
    op.execute("DROP TYPE IF EXISTS fraud_event_status;")
    op.execute("DROP TYPE IF EXISTS fraud_risk_level;")
    op.execute("DROP TYPE IF EXISTS fraud_rule_type;")
    op.execute("DROP TYPE IF EXISTS ledger_txn_status;")
    op.execute("DROP TYPE IF EXISTS ledger_entry_type;")
    op.execute("DROP TYPE IF EXISTS account_normality;")
    op.execute("DROP TYPE IF EXISTS account_type;")
    op.execute("DROP TYPE IF EXISTS transaction_status;")
    op.execute("DROP TYPE IF EXISTS transaction_type;")
    op.execute("DROP TYPE IF EXISTS wallet_status;")
    op.execute("DROP TYPE IF EXISTS user_role;")