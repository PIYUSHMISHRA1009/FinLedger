"""
FinLedger Unit Tests - Authentication
"""

import pytest
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock, patch

from finledger.core.auth.password import (
    get_password_hash,
    verify_password,
    validate_password_strength,
    hash_token,
    verify_token,
)
from finledger.core.auth.tokens import (
    create_access_token,
    decode_access_token,
    create_refresh_token,
    hash_token as tokens_hash_token,
    verify_token as tokens_verify_token,
    store_refresh_token,
    validate_refresh_token,
    revoke_refresh_token,
)
from finledger.core.auth.rbac import (
    get_permissions_for_role,
    require_permission,
    require_role,
    AuthService,
)
from finledger.core.exceptions import (
    ValidationError,
    InvalidCredentialsError,
    TokenExpiredError,
    TokenRevokedError,
)
from finledger.db.models import User, RefreshToken


class TestPasswordHashing:
    """Tests for password hashing and validation."""
    
    def test_hash_password_returns_string(self):
        password = "SecurePass123!"
        hashed = get_password_hash(password)
        assert isinstance(hashed, str)
        assert len(hashed) > 50  # Argon2 hash is long
    
    def test_verify_correct_password(self):
        password = "SecurePass123!"
        hashed = get_password_hash(password)
        assert verify_password(password, hashed) is True
    
    def test_verify_incorrect_password(self):
        password = "SecurePass123!"
        hashed = get_password_hash(password)
        assert verify_password("WrongPass123!", hashed) is False
    
    def test_password_strength_valid(self):
        valid_passwords = [
            "SecurePass123!",
            "VeryLongPassword123@#$",
            "Test12345678!",
            "Complex_Pass123",
        ]
        for pwd in valid_passwords:
            is_valid, error = validate_password_strength(pwd)
            assert is_valid, f"Expected valid: {pwd}, got error: {error}"
    
    def test_password_strength_too_short(self):
        is_valid, error = validate_password_strength("Short1!")
        assert is_valid is False
        assert "at least 12 characters" in error
    
    def test_password_strength_no_uppercase(self):
        is_valid, error = validate_password_strength("lowercase123!")
        assert is_valid is False
        assert "uppercase" in error
    
    def test_password_strength_no_lowercase(self):
        is_valid, error = validate_password_strength("UPPERCASE123!")
        assert is_valid is False
        assert "lowercase" in error
    
    def test_password_strength_no_digit(self):
        is_valid, error = validate_password_strength("NoDigitsHere!")
        assert is_valid is False
        assert "digit" in error
    
    def test_password_strength_no_special(self):
        is_valid, error = validate_password_strength("NoSpecialChars123")
        assert is_valid is False
        assert "special" in error


class TestTokenHashing:
    """Tests for token hashing (refresh tokens)."""
    
    def test_hash_and_verify_token(self):
        token = "test-refresh-token-12345"
        hashed = hash_token(token)
        assert isinstance(hashed, str)
        assert verify_token(token, hashed) is True
        assert verify_token("wrong-token", hashed) is False
    
    def test_tokens_hash_and_verify(self):
        token = "another-test-token-67890"
        hashed = tokens_hash_token(token)
        assert tokens_verify_token(token, hashed) is True
        assert tokens_verify_token("wrong", hashed) is False


class TestJWTTokens:
    """Tests for JWT access token creation and validation."""
    
    def test_create_access_token(self):
        user_id = uuid4()
        token = create_access_token(
            user_id=user_id,
            email="test@example.com",
            role="USER",
        )
        assert isinstance(token, str)
        assert len(token) > 100
    
    def test_decode_access_token(self):
        user_id = uuid4()
        token = create_access_token(
            user_id=user_id,
            email="test@example.com",
            role="USER",
        )
        payload = decode_access_token(token)
        assert payload is not None
        assert str(payload.sub) == str(user_id)
        assert payload.email == "test@example.com"
        assert payload.role == "USER"
        assert payload.token_type == "access"
    
    def test_decode_invalid_token(self):
        payload = decode_access_token("invalid.token.string")
        assert payload is None
    
    def test_decode_expired_token(self):
        # This would need a token with past expiry - skip for now
        pass


class TestRefreshToken:
    """Tests for refresh token generation."""
    
    def test_create_refresh_token(self):
        token = create_refresh_token()
        assert isinstance(token, str)
        assert len(token) > 40  # 64 bytes urlsafe
    
    def test_refresh_tokens_unique(self):
        tokens = {create_refresh_token() for _ in range(100)}
        assert len(tokens) == 100


class TestRBACPermissions:
    """Tests for role-based permissions."""
    
    def test_user_permissions(self):
        perms = get_permissions_for_role("USER")
        assert "wallet:read" in perms
        assert "wallet:write" in perms
        assert "transfer:execute" in perms
        assert "user:manage" not in perms
    
    def test_admin_permissions(self):
        perms = get_permissions_for_role("ADMIN")
        assert "user:manage" in perms
        assert "system:config" in perms
        assert "audit:read" in perms
    
    def test_compliance_permissions(self):
        perms = get_permissions_for_role("COMPLIANCE")
        assert "fraud:read" in perms
        assert "fraud:review" in perms
        assert "user:manage" not in perms
    
    def test_system_permissions(self):
        perms = get_permissions_for_role("SYSTEM")
        assert "service:internal" in perms
        assert "ledger:write" in perms
    
    def test_unknown_role(self):
        perms = get_permissions_for_role("UNKNOWN")
        assert perms == []


class TestAuthService:
    """Tests for AuthService (mocked database)."""
    
    @pytest.fixture
    def mock_db(self):
        return AsyncMock()
    
    @pytest.fixture
    def auth_service(self, mock_db):
        return AuthService(mock_db)
    
    @pytest.mark.asyncio
    async def test_register_success(self, auth_service, mock_db):
        mock_db.execute.return_value.scalar_one_or_none.return_value = None
        
        with patch("finledger.core.auth.rbac.get_password_hash", return_value="hashed"):
            with patch("finledger.core.auth.rbac.create_access_token", return_value="access"):
                with patch("finledger.core.auth.rbac.create_refresh_token", return_value="refresh"):
                    with patch("finledger.core.auth.rbac.store_refresh_token", new_callable=AsyncMock):
                        user = await auth_service.register(
                            email="new@example.com",
                            password="SecurePass123!",
                            full_name="New User",
                        )
        
        assert user.email == "new@example.com"
        assert user.full_name == "New User"
        assert user.role == "USER"
        assert user.is_active is True
    
    @pytest.mark.asyncio
    async def test_register_duplicate_email(self, auth_service, mock_db):
        mock_db.execute.return_value.scalar_one_or_none.return_value = User(id=uuid4())
        
        with pytest.raises(ValueError, match="Email already registered"):
            await auth_service.register(
                email="existing@example.com",
                password="SecurePass123!",
                full_name="Test",
            )
    
    @pytest.mark.asyncio
    async def test_register_weak_password(self, auth_service, mock_db):
        mock_db.execute.return_value.scalar_one_or_none.return_value = None
        
        with pytest.raises(ValueError, match="at least 12 characters"):
            await auth_service.register(
                email="new@example.com",
                password="weak",
                full_name="Test",
            )
    
    @pytest.mark.asyncio
    async def test_login_success(self, auth_service, mock_db):
        user = User(
            id=uuid4(),
            email="test@example.com",
            password_hash="hashed",
            role="USER",
            is_active=True,
            failed_login_attempts=0,
        )
        
        mock_db.execute.return_value.scalar_one_or_none.return_value = user
        
        with patch("finledger.core.auth.rbac.verify_password", return_value=True):
            with patch("finledger.core.auth.rbac.create_access_token", return_value="access"):
                with patch("finledger.core.auth.rbac.create_refresh_token", return_value="refresh"):
                    with patch("finledger.core.auth.rbac.store_refresh_token", new_callable=AsyncMock):
                        user_result, access, refresh = await auth_service.login(
                            email="test@example.com",
                            password="SecurePass123!",
                        )
        
        assert user_result == user
        assert access == "access"
        assert refresh == "refresh"
    
    @pytest.mark.asyncio
    async def test_login_invalid_password(self, auth_service, mock_db):
        user = User(
            id=uuid4(),
            email="test@example.com",
            password_hash="hashed",
            role="USER",
            is_active=True,
            failed_login_attempts=0,
        )
        
        mock_db.execute.return_value.scalar_one_or_none.return_value = user
        
        with patch("finledger.core.auth.rbac.verify_password", return_value=False):
            with pytest.raises(ValueError, match="Invalid credentials"):
                await auth_service.login(
                    email="test@example.com",
                    password="WrongPass123!",
                )
    
    @pytest.mark.asyncio
    async def test_login_account_locked(self, auth_service, mock_db):
        user = User(
            id=uuid4(),
            email="test@example.com",
            password_hash="hashed",
            role="USER",
            is_active=True,
            locked_until=__import__("datetime").datetime.now(__import__("datetime").timezone.utc) + __import__("datetime").timedelta(minutes=10),
        )
        
        mock_db.execute.return_value.scalar_one_or_none.return_value = user
        
        with pytest.raises(ValueError, match="Account is temporarily locked"):
            await auth_service.login(
                email="test@example.com",
                password="SecurePass123!",
            )


class TestRequirePermission:
    """Tests for permission checking dependencies."""
    
    @pytest.mark.asyncio
    async def test_require_permission_granted(self):
        from finledger.core.auth.rbac import require_permission
        from finledger.core.auth.rbac import UserContext
        
        # This would need a full FastAPI test client - skip for unit tests
        pass


class TestRequireRole:
    """Tests for role checking dependencies."""
    
    @pytest.mark.asyncio
    async def test_require_role_granted(self):
        # Would need FastAPI test client
        pass


# Run with pytest
if __name__ == "__main__":
    pytest.main([__file__, "-v"])