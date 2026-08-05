"""
FinLedger Integration Tests - API Endpoints
"""

import pytest
from decimal import Decimal
from uuid import uuid4
from datetime import datetime, timezone

from httpx import AsyncClient


class TestAuthIntegration:
    """Integration tests for authentication endpoints."""
    
    @pytest.mark.asyncio
    async def test_register_success(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "newuser@example.com",
                "password": "SecurePass123!",
                "full_name": "New User",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        assert "user" in data
        assert data["user"]["email"] == "newuser@example.com"
        assert data["user"]["role"] == "USER"
    
    @pytest.mark.asyncio
    async def test_register_duplicate_email(self, client: AsyncClient, auth_headers: dict):
        # First register a user
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": "duplicate@example.com",
                "password": "SecurePass123!",
                "full_name": "First User",
            },
        )
        
        # Try to register same email
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "duplicate@example.com",
                "password": "AnotherPass123!",
                "full_name": "Second User",
            },
        )
        assert response.status_code == 400
        assert "already registered" in response.json()["error"]["message"]
    
    @pytest.mark.asyncio
    async def test_register_weak_password(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "weakpass@example.com",
                "password": "weak",
                "full_name": "Test User",
            },
        )
        assert response.status_code == 400
        assert "at least 12 characters" in response.json()["error"]["message"]
    
    @pytest.mark.asyncio
    async def test_login_success(self, client: AsyncClient, auth_headers: dict):
        # The auth_headers fixture already logs in
        assert "Authorization" in auth_headers
        assert auth_headers["Authorization"].startswith("Bearer ")
    
    @pytest.mark.asyncio
    async def test_login_invalid_credentials(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "nonexistent@example.com",
                "password": "WrongPass123!",
            },
        )
        assert response.status_code == 401
        assert "Invalid credentials" in response.json()["error"]["message"]
    
    @pytest.mark.asyncio
    async def test_refresh_token_success(self, client: AsyncClient, auth_headers: dict):
        # Get refresh token from login
        login_response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "test@example.com",
                "password": "TestPass123!",
            },
        )
        refresh_token = login_response.json()["refresh_token"]
        
        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        # New refresh token should be different
        assert data["refresh_token"] != refresh_token
    
    @pytest.mark.asyncio
    async def test_refresh_token_reuse_detected(self, client: AsyncClient, auth_headers: dict):
        # Get refresh token
        login_response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "test@example.com",
                "password": "TestPass123!",
            },
        )
        refresh_token = login_response.json()["refresh_token"]
        
        # Use it once
        await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
        
        # Try to use it again - should detect reuse
        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )
        assert response.status_code == 401
        assert "reuse" in response.json()["error"]["message"].lower()
    
    @pytest.mark.asyncio
    async def test_logout(self, client: AsyncClient, auth_headers: dict):
        # Get refresh token
        login_response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "test@example.com",
                "password": "TestPass123!",
            },
        )
        refresh_token = login_response.json()["refresh_token"]
        
        response = await client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": refresh_token},
            headers=auth_headers,
        )
        assert response.status_code == 204
    
    @pytest.mark.asyncio
    async def test_get_me(self, client: AsyncClient, auth_headers: dict):
        response = await client.get("/api/v1/auth/me", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "test@example.com"
        assert data["role"] == "USER"


class TestWalletIntegration:
    """Integration tests for wallet endpoints."""
    
    @pytest.mark.asyncio
    async def test_create_wallet(self, client: AsyncClient, auth_headers: dict):
        response = await client.post(
            "/api/v1/wallets",
            json={"currency": "USD", "name": "Test Wallet"},
            headers=auth_headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["currency"] == "USD"
        assert data["name"] == "Test Wallet"
        assert data["status"] == "ACTIVE"
        assert "id" in data
    
    @pytest.mark.asyncio
    async def test_create_wallet_duplicate(self, client: AsyncClient, auth_headers: dict):
        await client.post(
            "/api/v1/wallets",
            json={"currency": "USD", "name": "Test Wallet"},
            headers=auth_headers,
        )
        
        response = await client.post(
            "/api/v1/wallets",
            json={"currency": "USD", "name": "Test Wallet"},
            headers=auth_headers,
        )
        assert response.status_code == 400
        assert "already exists" in response.json()["error"]["message"]
    
    @pytest.mark.asyncio
    async def test_list_wallets(self, client: AsyncClient, auth_headers: dict):
        await client.post(
            "/api/v1/wallets",
            json={"currency": "USD", "name": "Wallet 1"},
            headers=auth_headers,
        )
        await client.post(
            "/api/v1/wallets",
            json={"currency": "EUR", "name": "Wallet 2"},
            headers=auth_headers,
        )
        
        response = await client.get("/api/v1/wallets", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 2
        assert len(data["items"]) >= 2
    
    @pytest.mark.asyncio
    async def test_get_wallet_balance(self, client: AsyncClient, auth_headers: dict):
        create_response = await client.post(
            "/api/v1/wallets",
            json={"currency": "USD", "name": "Balance Test"},
            headers=auth_headers,
        )
        wallet_id = create_response.json()["id"]
        
        response = await client.get(
            f"/api/v1/wallets/{wallet_id}/balance",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert "posted_balance" in data
        assert "pending_balance" in data
        assert "available_balance" in data
    
    @pytest.mark.asyncio
    async def test_deposit(self, client: AsyncClient, auth_headers: dict):
        create_response = await client.post(
            "/api/v1/wallets",
            json={"currency": "USD", "name": "Deposit Test"},
            headers=auth_headers,
        )
        wallet_id = create_response.json()["id"]
        
        response = await client.post(
            f"/api/v1/wallets/{wallet_id}/deposit",
            json={"amount": "100.00", "description": "Test deposit"},
            headers={**auth_headers, "Idempotency-Key": "deposit-test-123"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["type"] == "DEPOSIT"
        assert data["status"] == "COMPLETED"
        assert data["amount"] == "100.00"
    
    @pytest.mark.asyncio
    async def test_deposit_idempotency(self, client: AsyncClient, auth_headers: dict):
        create_response = await client.post(
            "/api/v1/wallets",
            json={"currency": "USD", "name": "Idempotency Test"},
            headers=auth_headers,
        )
        wallet_id = create_response.json()["id"]
        idempotency_key = "idem-test-456"
        
        # First request
        response1 = await client.post(
            f"/api/v1/wallets/{wallet_id}/deposit",
            json={"amount": "50.00", "description": "First"},
            headers={**auth_headers, "Idempotency-Key": idempotency_key},
        )
        assert response1.status_code == 201
        
        # Second request with same key - should return cached response
        response2 = await client.post(
            f"/api/v1/wallets/{wallet_id}/deposit",
            json={"amount": "50.00", "description": "First"},
            headers={**auth_headers, "Idempotency-Key": idempotency_key},
        )
        assert response2.status_code == 201
        # Should be same transaction ID
        assert response1.json()["id"] == response2.json()["id"]
    
    @pytest.mark.asyncio
    async def test_deposit_idempotency_conflict(self, client: AsyncClient, auth_headers: dict):
        create_response = await client.post(
            "/api/v1/wallets",
            json={"currency": "USD", "name": "Conflict Test"},
            headers=auth_headers,
        )
        wallet_id = create_response.json()["id"]
        idempotency_key = "conflict-test-789"
        
        # First request
        await client.post(
            f"/api/v1/wallets/{wallet_id}/deposit",
            json={"amount": "50.00", "description": "First"},
            headers={**auth_headers, "Idempotency-Key": idempotency_key},
        )
        
        # Second request with same key but different amount
        response = await client.post(
            f"/api/v1/wallets/{wallet_id}/deposit",
            json={"amount": "100.00", "description": "Different amount"},
            headers={**auth_headers, "Idempotency-Key": idempotency_key},
        )
        assert response.status_code == 409
        assert "conflict" in response.json()["error"]["message"].lower()
    
    @pytest.mark.asyncio
    async def test_withdraw(self, client: AsyncClient, auth_headers: dict):
        create_response = await client.post(
            "/api/v1/wallets",
            json={"currency": "USD", "name": "Withdraw Test"},
            headers=auth_headers,
        )
        wallet_id = create_response.json()["id"]
        
        # First deposit some funds
        await client.post(
            f"/api/v1/wallets/{wallet_id}/deposit",
            json={"amount": "200.00", "description": "Initial deposit"},
            headers={**auth_headers, "Idempotency-Key": "deposit-for-withdraw"},
        )
        
        response = await client.post(
            f"/api/v1/wallets/{wallet_id}/withdraw",
            json={"amount": "50.00", "description": "Test withdrawal"},
            headers={**auth_headers, "Idempotency-Key": "withdraw-test-123"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["type"] == "WITHDRAWAL"
        assert data["status"] == "COMPLETED"
        assert data["amount"] == "50.00"
    
    @pytest.mark.asyncio
    async def test_withdraw_insufficient_funds(self, client: AsyncClient, auth_headers: dict):
        create_response = await client.post(
            "/api/v1/wallets",
            json={"currency": "USD", "name": "Insufficient Test"},
            headers=auth_headers,
        )
        wallet_id = create_response.json()["id"]
        
        response = await client.post(
            f"/api/v1/wallets/{wallet_id}/withdraw",
            json={"amount": "1000.00", "description": "Too much"},
            headers={**auth_headers, "Idempotency-Key": "withdraw-insufficient"},
        )
        assert response.status_code == 409
        assert "insufficient" in response.json()["error"]["message"].lower()
    
    @pytest.mark.asyncio
    async def test_transfer(self, client: AsyncClient, auth_headers: dict):
        # Create two wallets
        wallet1_resp = await client.post(
            "/api/v1/wallets",
            json={"currency": "USD", "name": "Source Wallet"},
            headers=auth_headers,
        )
        wallet1_id = wallet1_resp.json()["id"]
        
        # Need second user for destination wallet - use admin to create another user
        # For simplicity, create another wallet for same user
        wallet2_resp = await client.post(
            "/api/v1/wallets",
            json={"currency": "USD", "name": "Dest Wallet"},
            headers=auth_headers,
        )
        wallet2_id = wallet2_resp.json()["id"]
        
        # Deposit to source wallet
        await client.post(
            f"/api/v1/wallets/{wallet1_id}/deposit",
            json={"amount": "200.00", "description": "Fund source"},
            headers={**auth_headers, "Idempotency-Key": "deposit-for-transfer"},
        )
        
        # Transfer
        response = await client.post(
            f"/api/v1/wallets/{wallet1_id}/transfer",
            json={
                "amount": "50.00",
                "destination_wallet_id": wallet2_id,
                "description": "Test transfer",
            },
            headers={**auth_headers, "Idempotency-Key": "transfer-test-123"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["type"] == "TRANSFER_OUT"
        assert data["status"] == "COMPLETED"
        assert data["amount"] == "50.00"
        assert "fraud_risk_score" in data
    
    @pytest.mark.asyncio
    async def test_transfer_same_wallet(self, client: AsyncClient, auth_headers: dict):
        create_response = await client.post(
            "/api/v1/wallets",
            json={"currency": "USD", "name": "Same Wallet Test"},
            headers=auth_headers,
        )
        wallet_id = create_response.json()["id"]
        
        response = await client.post(
            f"/api/v1/wallets/{wallet_id}/transfer",
            json={
                "amount": "50.00",
                "destination_wallet_id": wallet_id,
                "description": "Self transfer",
            },
            headers={**auth_headers, "Idempotency-Key": "self-transfer"},
        )
        assert response.status_code == 409
        assert "same wallet" in response.json()["error"]["message"].lower()
    
    @pytest.mark.asyncio
    async def test_transfer_currency_mismatch(self, client: AsyncClient, auth_headers: dict):
        wallet1_resp = await client.post(
            "/api/v1/wallets",
            json={"currency": "USD", "name": "USD Wallet"},
            headers=auth_headers,
        )
        wallet1_id = wallet1_resp.json()["id"]
        
        wallet2_resp = await client.post(
            "/api/v1/wallets",
            json={"currency": "EUR", "name": "EUR Wallet"},
            headers=auth_headers,
        )
        wallet2_id = wallet2_resp.json()["id"]
        
        response = await client.post(
            f"/api/v1/wallets/{wallet1_id}/transfer",
            json={
                "amount": "50.00",
                "destination_wallet_id": wallet2_id,
                "description": "Cross currency",
            },
            headers={**auth_headers, "Idempotency-Key": "cross-currency"},
        )
        assert response.status_code == 409
        assert "currency mismatch" in response.json()["error"]["message"].lower()


class TestHealthIntegration:
    """Integration tests for health endpoints."""
    
    @pytest.mark.asyncio
    async def test_health(self, client: AsyncClient):
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data
    
    @pytest.mark.asyncio
    async def test_health_live(self, client: AsyncClient):
        response = await client.get("/health/live")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "alive"
    
    @pytest.mark.asyncio
    async def test_health_ready(self, client: AsyncClient):
        response = await client.get("/health/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ["ready", "not_ready"]
        assert "checks" in data
        assert "database" in data["checks"]
    
    @pytest.mark.asyncio
    async def test_metrics(self, client: AsyncClient):
        response = await client.get("/metrics")
        assert response.status_code == 200
        assert "http_requests_total" in response.text
        assert "http_request_duration_seconds" in response.text


class TestAdminIntegration:
    """Integration tests for admin/compliance endpoints."""
    
    @pytest.mark.asyncio
    async def test_fraud_events_admin(self, client: AsyncClient, admin_headers: dict):
        response = await client.get("/api/v1/fraud/events", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
    
    @pytest.mark.asyncio
    async def test_fraud_events_unauthorized(self, client: AsyncClient, auth_headers: dict):
        response = await client.get("/api/v1/fraud/events", headers=auth_headers)
        assert response.status_code == 403
    
    @pytest.mark.asyncio
    async def test_fraud_rules_admin(self, client: AsyncClient, admin_headers: dict):
        response = await client.get("/api/v1/fraud/rules", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 10  # Seeded rules
    
    @pytest.mark.asyncio
    async def test_fraud_rules_unauthorized(self, client: AsyncClient, auth_headers: dict):
        response = await client.get("/api/v1/fraud/rules", headers=auth_headers)
        assert response.status_code == 403
    
    @pytest.mark.asyncio
    async def test_create_fraud_rule_admin(self, client: AsyncClient, admin_headers: dict):
        response = await client.post(
            "/api/v1/fraud/rules",
            json={
                "code": "TEST_RULE_001",
                "name": "Test Rule",
                "description": "Test rule for integration",
                "rule_type": "AMOUNT_THRESHOLD",
                "weight": "0.250",
                "parameters": {"threshold_amount": "50000"},
                "active": True,
                "priority": 50,
            },
            headers=admin_headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["code"] == "TEST_RULE_001"
        assert data["weight"] == "0.250"
    
    @pytest.mark.asyncio
    async def test_ledger_trial_balance_compliance(self, client: AsyncClient, admin_headers: dict):
        response = await client.get("/api/v1/ledger/trial-balance", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert "accounts" in data
        assert "total_debits" in data
        assert "total_credits" in data
        assert "balanced" in data
        assert data["balanced"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])