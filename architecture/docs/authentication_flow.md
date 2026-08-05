# FinLedger Authentication Flow Documentation

## Overview

FinLedger implements a secure, standards-compliant authentication system using JWT (JSON Web Tokens) with refresh token rotation, Role-Based Access Control (RBAC), and defense-in-depth security measures.

## Token Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    AUTHENTICATION FLOW                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────┐     ┌──────────┐     ┌──────────┐               │
│  │  CLIENT  │────▶│  AUTH    │────▶│  REDIS   │               │
│  │          │     │  SERVICE │     │  CACHE   │               │
│  └──────────┘     └────┬─────┘     └──────────┘               │
│         │              │                                      │
│         │              ▼                                      │
│         │       ┌──────────┐                                   │
│         │       │POSTGRESQL│                                   │
│         │       │  USERS   │                                   │
│         │       │ REFRESH  │                                   │
│         │       │  TOKENS  │                                   │
│         │       └──────────┘                                   │
│         │                                                      │
│         ▼                                                      │
│  ┌─────────────────────────────────────────────┐              │
│  │           TOKEN PAIR                        │              │
│  │  ┌─────────────────┐  ┌─────────────────┐  │              │
│  │  │  ACCESS TOKEN   │  │  REFRESH TOKEN  │  │              │
│  │  │  (JWT, 15 min)  │  │  (Opaque, 7d)   │  │              │
│  │  │  • user_id      │  │  • token_hash   │  │              │
│  │  │  • email        │  │  • user_id      │  │              │
│  │  │  • role         │  │  • expires_at   │  │              │
│  │  │  • permissions  │  │  • device_info  │  │              │
│  │  │  • jti (unique) │  │  • rotated      │  │              │
│  │  └─────────────────┘  └─────────────────┘  │              │
│  └─────────────────────────────────────────────┘              │
└─────────────────────────────────────────────────────────────────┘
```

## Access Token (JWT)

### Claims Structure
```json
{
  "iss": "finledger.io",
  "sub": "user_uuid",
  "aud": "finledger-api",
  "iat": 1705312200,
  "exp": 1705313100,
  "jti": "unique-token-id",
  "email": "user@example.com",
  "role": "USER",
  "permissions": ["wallet:read", "wallet:write", "transfer:execute"],
  "token_type": "access"
}
```

### Security Properties
- **Algorithm**: RS256 (RSA signature with SHA-256)
- **Key Rotation**: Automatic via JWKS endpoint
- **Expiration**: 15 minutes (900 seconds)
- **Unique JTI**: Prevents token replay
- **Audience/Issuer Validation**: Prevents cross-service misuse

## Refresh Token

### Storage (Database + Redis Cache)
```sql
-- refresh_tokens table
id              UUID PRIMARY KEY
user_id         UUID REFERENCES users(id)
token_hash      VARCHAR(255) UNIQUE  -- Argon2id hash
expires_at      TIMESTAMPTZ          -- 7 days from issuance
revoked         BOOLEAN DEFAULT FALSE
revoked_at      TIMESTAMPTZ
revoked_reason  VARCHAR(255)
user_agent      TEXT
ip_address      INET
created_at      TIMESTAMPTZ
```

### Rotation Policy
1. **Single-use**: Each refresh token can only be used once
2. **Rotation**: On refresh, old token is revoked, new pair issued
3. **Reuse Detection**: If revoked token presented → revoke ALL user tokens (account takeover protection)
4. **Device Binding**: Optional binding to device fingerprint

## Authentication Endpoints

### 1. User Registration
```http
POST /api/v1/auth/register
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "SecurePass123!",
  "full_name": "John Doe"
}
```

**Flow:**
1. Validate email format, password strength (min 12 chars, complexity)
2. Check email uniqueness
3. Hash password with Argon2id (memory=64MB, iterations=3, parallelism=4)
4. Create user (is_verified=false, role=USER)
5. Generate email verification token (24hr expiry)
6. Create access + refresh token pair
7. Store refresh token hash in DB
8. Return tokens + user info

**Rate Limit**: 10 requests/minute per IP

### 2. User Login
```http
POST /api/v1/auth/login
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "SecurePass123!"
}
```

**Flow:**
1. Find user by email
2. Check account status (active, not locked)
3. Verify password with Argon2id
4. Reset failed_login_attempts on success
5. Check if 2FA enabled (future)
6. Generate new token pair
7. Store refresh token
8. Update last_login_at
9. Return tokens

**Failure Handling:**
- Increment failed_login_attempts
- Lock after 5 failures for 15 minutes
- Log security event

**Rate Limit**: 10 requests/minute per IP

### 3. Token Refresh
```http
POST /api/v1/auth/refresh
Content-Type: application/json

{
  "refresh_token": "opaque-token-string"
}
```

**Flow:**
1. Hash presented token with Argon2id
2. Look up in refresh_tokens table
3. Validate: not revoked, not expired, matches user
4. **Critical**: Check for reuse (token already revoked)
   - If reused → revoke ALL user tokens, alert security
5. Revoke current token (mark revoked, set revoked_at)
6. Generate new access + refresh token pair
7. Store new refresh token hash
9. Return new token pair

**Rate Limit**: 5 requests/minute per user

### 4. Logout
```http
POST /api/v1/auth/logout
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "refresh_token": "opaque-token-string"
}
```

**Flow:**
1. Validate access token
2. Hash and revoke refresh token
3. Add access token JTI to Redis blocklist (TTL = remaining token life)
4. Return 204

### 5. Get Current User
```http
GET /api/v1/auth/me
Authorization: Bearer <access_token>
```

Returns user profile from JWT claims (no DB lookup needed).

## Password Security

### Requirements (Enforced at Registration/Change)
- Minimum 12 characters
- At least 1 uppercase, 1 lowercase, 1 digit, 1 special char
- Not in common password list (HaveIBeenPwned API check)
- Not similar to email/name (Levenshtein distance)

### Hashing: Argon2id
```python
# Parameters (OWASP recommended)
memory_cost = 65536      # 64 MB
time_cost = 3            # iterations
parallelism = 4          # threads
hash_length = 32         # bytes
salt_length = 16         # bytes
```

### Password Reset Flow
1. `POST /auth/forgot-password` → Email with reset token (1hr expiry)
2. `POST /auth/reset-password` → Validate token, hash new password
3. Revoke ALL refresh tokens for user
4. Return success

## Role-Based Access Control (RBAC)

### Roles
| Role | Description | Permissions |
|------|-------------|-------------|
| `USER` | Standard customer | wallet:read, wallet:write, transfer:execute, ledger:read |
| `ADMIN` | Platform administrator | All USER + user:manage, system:config, audit:read |
| `COMPLIANCE` | Fraud/compliance team | All USER + fraud:read, fraud:review, transaction:read_all |
| `SYSTEM` | Internal services | service:internal, ledger:write, webhook:send |

### Permission Format
`resource:action` (e.g., `wallet:read`, `transfer:execute`, `fraud:review`)

### Enforcement
- **Middleware**: Validates JWT, extracts role/permissions
- **Dependency Injection**: `require_permission("transfer:execute")`
- **Route-level**: `@router.post(..., dependencies=[Depends(require_role("ADMIN"))])`

## Middleware Stack

```python
# Request processing order
1. RequestIDMiddleware      # Generate/extract X-Request-ID
2. LoggingMiddleware        # Structured request/response logging
3. RateLimitMiddleware      # Token bucket per IP/user
4. AuthMiddleware           # JWT validation, user context
5. RBACMiddleware           # Permission checks
6. IdempotencyMiddleware    # Check/store idempotency keys
```

### Auth Middleware Logic
```python
async def auth_middleware(request: Request, call_next):
    # 1. Extract Bearer token
    token = extract_bearer_token(request)
    
    # 2. Check Redis blocklist (logout/revocation)
    if await redis.exists(f"blocklist:{token.jti}"):
        return 401 {"error": "TOKEN_REVOKED"}
    
    # 3. Validate JWT signature, exp, iss, aud
    claims = jwt.decode(token, public_key, algorithms=["RS256"])
    
    # 4. Attach user context to request.state
    request.state.user = UserContext(
        user_id=claims["sub"],
        email=claims["email"],
        role=claims["role"],
        permissions=claims["permissions"],
        token_jti=claims["jti"]
    )
    
    return await call_next(request)
```

## Security Headers

All responses include:
```
Strict-Transport-Security: max-age=31536000; includeSubDomains
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Content-Security-Policy: default-src 'none'; frame-ancestors 'none'
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: geolocation=(), microphone=(), camera=()
```

## CORS Policy

```python
CORS_CONFIG = {
    "allow_origins": ["https://app.finledger.io", "https://admin.finledger.io"],
    "allow_credentials": True,
    "allow_methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    "allow_headers": ["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
    "expose_headers": ["X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"],
    "max_age": 86400
}
```

## Session Management

### Concurrent Sessions
- Maximum 5 active refresh tokens per user
- Oldest revoked when limit exceeded
- Admin can view/revoke all sessions

### Device Tracking
```json
{
  "user_agent": "Mozilla/5.0...",
  "ip_address": "192.168.1.1",
  "device_fingerprint": "fp_abc123",
  "location": {"country": "US", "city": "New York"},
  "first_seen": "2024-01-10T08:00:00Z",
  "last_seen": "2024-01-15T10:30:00Z"
}
```

## Security Event Logging

All auth events logged to audit_logs:
- `auth.login.success`
- `auth.login.failed`
- `auth.register`
- `auth.token_refresh`
- `auth.token_reuse_detected` (CRITICAL)
- `auth.logout`
- `auth.password_change`
- `auth.account_locked`
- `auth.mfa_enabled` (future)

## Threat Mitigations

| Threat | Mitigation |
|--------|------------|
| Token theft | Short JWT expiry (15min), refresh rotation, blocklist |
| Credential stuffing | Rate limits, account lockout, Argon2id |
| Token replay | JTI uniqueness, Redis blocklist |
| Refresh token reuse | Single-use, reuse detection → full revocation |
| Session fixation | New token pair on login, rotate on privilege change |
| Timing attacks | Constant-time password verification |
| Brute force | Rate limiting, exponential backoff, CAPTCHA (future) |

## Testing Checklist

- [ ] Valid login returns token pair
- [ ] Invalid password returns 401, increments counter
- [ ] Lockout after 5 failures
- [ ] Refresh token rotation works
- [ ] Refresh token reuse detection triggers full revocation
- [ ] Expired access token rejected
- [ ] Revoked refresh token rejected
- [ ] Logout adds JTI to blocklist
- [ ] Blocklisted access token rejected
- [ ] RBAC enforces permissions correctly
- [ ] Rate limits enforced per endpoint
- [ ] Password strength enforced
- [ ] Argon2id parameters match spec
- [ ] Email verification flow works
- [ ] Password reset revokes all sessions