"""
FinLedger Password Hashing Module

Secure password hashing using Argon2id with configurable parameters.
"""

import secrets
from typing import Tuple

from passlib.hash import argon2
from passlib.context import CryptContext

from finledger.api.config.settings import get_settings


# Password validation
MIN_PASSWORD_LENGTH = 12
REQUIRE_UPPERCASE = True
REQUIRE_LOWERCASE = True
REQUIRE_DIGIT = True
REQUIRE_SPECIAL = True


def validate_password_strength(password: str) -> Tuple[bool, str]:
    """
    Validate password meets strength requirements.
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        return False, f"Password must be at least {MIN_PASSWORD_LENGTH} characters"
    
    if REQUIRE_UPPERCASE and not any(c.isupper() for c in password):
        return False, "Password must contain at least one uppercase letter"
    
    if REQUIRE_LOWERCASE and not any(c.islower() for c in password):
        return False, "Password must contain at least one lowercase letter"
    
    if REQUIRE_DIGIT and not any(c.isdigit() for c in password):
        return False, "Password must contain at least one digit"
    
    if REQUIRE_SPECIAL and not any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in password):
        return False, "Password must contain at least one special character"
    
    # Check for common patterns
    if password.lower() in ["password", "admin", "123456", "qwerty"]:
        return False, "Password is too common"
    
    return True, ""


def get_password_hash(password: str) -> str:
    """
    Hash password using Argon2id.
    
    Uses settings from configuration for memory, time, and parallelism costs.
    """
    settings = get_settings()
    
    pwd_context = CryptContext(
        schemes=["argon2"],
        deprecated="auto",
        argon2__memory_cost=settings.ARGON2_MEMORY_COST,
        argon2__time_cost=settings.ARGON2_TIME_COST,
        argon2__parallelism=settings.ARGON2_PARALLELISM,
        argon2__hash_len=32,
        argon2__salt_size=16,
    )
    
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain password against its hash.
    
    Uses constant-time comparison to prevent timing attacks.
    """
    pwd_context = CryptContext(
        schemes=["argon2"],
        deprecated="auto",
    )
    
    return pwd_context.verify(plain_password, hashed_password)


def generate_secure_token(length: int = 32) -> str:
    """Generate a cryptographically secure random token."""
    return secrets.token_urlsafe(length)


def hash_token(token: str) -> str:
    """Hash a token (e.g., refresh token) for storage."""
    # Use Argon2id for token hashing as well
    pwd_context = CryptContext(
        schemes=["argon2"],
        deprecated="auto",
        argon2__memory_cost=65536,
        argon2__time_cost=3,
        argon2__parallelism=4,
    )
    return pwd_context.hash(token)


def verify_token(plain_token: str, hashed_token: str) -> bool:
    """Verify a token against its hash."""
    pwd_context = CryptContext(
        schemes=["argon2"],
        deprecated="auto",
    )
    return pwd_context.verify(plain_token, hashed_token)