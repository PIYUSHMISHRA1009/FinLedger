"""
FinLedger Configuration Module

Centralized configuration management using Pydantic Settings.
Supports environment-specific configs with validation.
"""

import os
from pathlib import Path
from functools import lru_cache
from typing import List, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Application
    ENVIRONMENT: str = Field(default="development", description="Environment name")
    DEBUG: bool = Field(default=True, description="Debug mode")
    APP_NAME: str = Field(default="FinLedger", description="Application name")
    APP_VERSION: str = Field(default="1.0.0", description="Application version")

    # Database
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://finledger:dev_password@localhost:5432/finledger",
        description="PostgreSQL async connection URL",
    )
    DATABASE_POOL_SIZE: int = Field(default=20, description="Connection pool size")
    DATABASE_MAX_OVERFLOW: int = Field(default=10, description="Max overflow connections")
    DATABASE_POOL_TIMEOUT: int = Field(default=30, description="Pool timeout seconds")
    DATABASE_ECHO: bool = Field(default=False, description="Echo SQL queries")

    # Redis
    REDIS_URL: str = Field(default="redis://localhost:6379/0", description="Redis connection URL")
    REDIS_MAX_CONNECTIONS: int = Field(default=50, description="Max Redis connections")
    REDIS_DECODE_RESPONSES: bool = Field(default=True, description="Decode Redis responses")

    # JWT Authentication
    JWT_PRIVATE_KEY_PATH: str = Field(default="./keys/jwt_private.pem", description="Path to RSA private key")
    JWT_PUBLIC_KEY_PATH: str = Field(default="./keys/jwt_public.pem", description="Path to RSA public key")
    JWT_ALGORITHM: str = Field(default="RS256", description="JWT signing algorithm")
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=15, description="Access token expiry minutes")
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=7, description="Refresh token expiry days")
    JWT_ISSUER: str = Field(default="finledger.io", description="JWT issuer")
    JWT_AUDIENCE: str = Field(default="finledger-api", description="JWT audience")

    # Password Hashing
    PASSWORD_HASH_ALGORITHM: str = Field(default="argon2id", description="Password hash algorithm")
    ARGON2_MEMORY_COST: int = Field(default=65536, description="Argon2 memory cost (KB)")
    ARGON2_TIME_COST: int = Field(default=3, description="Argon2 time cost")
    ARGON2_PARALLELISM: int = Field(default=4, description="Argon2 parallelism")

    # Rate Limiting
    RATE_LIMIT_ENABLED: bool = Field(default=True, description="Enable rate limiting")
    RATE_LIMIT_DEFAULT: int = Field(default=100, description="Default rate limit per window")
    RATE_LIMIT_WINDOW_SECONDS: int = Field(default=60, description="Rate limit window seconds")

    # Fraud Engine
    FRAUD_ENABLED: bool = Field(default=True, description="Enable fraud detection")
    FRAUD_VELOCITY_WINDOW_SECONDS: int = Field(default=60, description="Velocity check window")
    FRAUD_VELOCITY_THRESHOLD: int = Field(default=10, description="Velocity threshold per window")
    FRAUD_CRITICAL_THRESHOLD: float = Field(default=0.85, description="Critical risk threshold")
    FRAUD_HIGH_THRESHOLD: float = Field(default=0.60, description="High risk threshold")
    FRAUD_MEDIUM_THRESHOLD: float = Field(default=0.30, description="Medium risk threshold")

    # Idempotency
    IDEMPOTENCY_TTL_HOURS: int = Field(default=24, description="Idempotency key TTL hours")

    # Logging
    LOG_LEVEL: str = Field(default="INFO", description="Logging level")
    LOG_FORMAT: str = Field(default="json", description="Log format (json/text)")

    # Monitoring
    PROMETHEUS_ENABLED: bool = Field(default=True, description="Enable Prometheus metrics")
    PROMETHEUS_PORT: int = Field(default=9090, description="Prometheus metrics port")

    # CORS
    CORS_ALLOW_ORIGINS: List[str] = Field(
        default=["http://localhost:3000", "http://localhost:8080"],
        description="Allowed CORS origins",
    )
    CORS_ALLOW_CREDENTIALS: bool = Field(default=True, description="Allow credentials in CORS")
    CORS_ALLOW_METHODS: List[str] = Field(
        default=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        description="Allowed HTTP methods",
    )
    CORS_ALLOW_HEADERS: List[str] = Field(
        default=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
        description="Allowed headers",
    )

    @field_validator("ENVIRONMENT")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        allowed = ["development", "staging", "production", "test"]
        if v not in allowed:
            raise ValueError(f"ENVIRONMENT must be one of {allowed}")
        return v

    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        v_upper = v.upper()
        if v_upper not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {allowed}")
        return v_upper

    @field_validator("LOG_FORMAT")
    @classmethod
    def validate_log_format(cls, v: str) -> str:
        allowed = ["json", "text"]
        if v not in allowed:
            raise ValueError(f"LOG_FORMAT must be one of {allowed}")
        return v

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT == "development"

    @property
    def is_test(self) -> bool:
        return self.ENVIRONMENT == "test"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# JWT Key Management
def ensure_keys_exist(settings: Settings) -> None:
    """Generate RSA key pair if not exists (development only)."""
    if settings.is_production:
        # In production, keys should be mounted from secrets manager
        return

    private_path = Path(settings.JWT_PRIVATE_KEY_PATH)
    public_path = Path(settings.JWT_PUBLIC_KEY_PATH)

    if private_path.exists() and public_path.exists():
        return

    private_path.parent.mkdir(parents=True, exist_ok=True)

    # Generate keys using cryptography
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    public_key = private_key.public_key()
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    private_path.write_bytes(private_pem)
    public_path.write_bytes(public_pem)

    # Set restrictive permissions
    private_path.chmod(0o600)
    public_path.chmod(0o644)