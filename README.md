# FinLedger

> **A production-grade digital wallet and transaction platform with immutable double-entry ledger, fraud detection engine, and financial transaction processing — built to showcase backend engineering excellence for top fintech companies.**

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-green.svg)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16+-blue.svg)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://www.docker.com/)
[![Tests](https://img.shields.io/badge/Tests-Pytest-orange.svg)](https://docs.pytest.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## 🎯 Project Overview

**FinLedger** is an original, production-ready fintech backend platform that demonstrates:

- **Immutable Double-Entry Ledger** — ACID-compliant, audit-ready financial records
- **Digital Wallet System** — Multi-currency wallets with balance types (Posted, Pending, Available)
- **Fraud Detection Engine** — Rule-based risk scoring with velocity checks
- **Secure Authentication** — JWT + Refresh tokens, RBAC, rate limiting
- **Clean Architecture** — Routes → Services → Repositories → Database
- **Observability** — Structured logging, request tracing, Prometheus metrics, health checks

---

## 🏗️ Architecture Highlights

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            FINLEDGER ARCHITECTURE                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────┐ │
│  │   CLIENT     │───▶│  API GATEWAY │───▶│  MIDDLEWARE  │───▶│  ROUTES  │ │
│  │  (Web/Mob)   │    │  (FastAPI)   │    │  (Auth,      │    │  (REST)  │ │
│  └──────────────┘    └──────────────┘    │   RateLimit, │    └────┬─────┘ │
│                                           │   Logging,   │         │       │
│                                           │   RequestID) │         ▼       │
│                                           └──────────────┘    ┌──────────┐ │
│                                                                │ SERVICES │ │
│                                           ┌──────────────┐    │ (Business │ │
│                                           │  REPOSITORIES│◀───│  Logic)  │ │
│                                           │  (Data       │    └────┬─────┘ │
│                                           │   Access)    │         │       │
│                                           └──────┬───────┘         ▼       │
│                                                  │            ┌──────────┐ │
│                                                  ▼            │ DATABASE │ │
│                                           ┌──────────────┐    │(PostgreSQL│ │
│                                           │   MODELS     │    │  + Redis)│ │
│                                           │  (SQLAlchemy)│    └──────────┘ │
│                                           └──────────────┘                │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│  CORE DOMAINS                                                              │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌──────────┐ │
│  │   LEDGER   │ │   WALLET   │ │TRANSACTION │ │   FRAUD    │ │  AUTH    │ │
│  │ Double-    │ │ Multi-     │ │ Processing │ │ Rule       │ │ JWT +    │ │
│  │ Entry Acct │ │ Currency   │ │ Engine     │ │ Engine     │ │ RBAC     │ │
│  └────────────┘ └────────────┘ └────────────┘ └────────────┘ └──────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## ✨ Features

### 🔐 Authentication & Authorization
- User registration with email verification
- JWT access tokens (15 min) + Refresh tokens (7 days)
- Role-Based Access Control (USER, ADMIN, COMPLIANCE)
- Secure password hashing (Argon2id)
- Rate limiting per IP/user
- Idempotent API endpoints

### 💰 Wallet Management
- Create multi-currency wallets
- Three balance types: **Posted**, **Pending**, **Available**
- Deposit, Withdraw, Transfer operations
- Real-time balance reconciliation
- Wallet locking for concurrent operations

### 📒 Double-Entry Ledger
- Immutable transaction history (append-only)
- Chart of Accounts with account types (Asset, Liability, Equity, Revenue, Expense)
- Every transaction = balanced debit/credit entries
- Account normality enforcement (debit-normal vs credit-normal)
- Transaction versioning for optimistic locking
- Balance queries with point-in-time consistency

### 🛡️ Fraud Detection Engine
| Rule | Description | Risk Weight |
|------|-------------|-------------|
| **Large Transaction** | Amount > 95th percentile | 0.35 |
| **Velocity Check** | > 10 txns/min or > 50 txns/hour | 0.30 |
| **Frequent Transfers** | > 5 transfers to same counterparty/day | 0.20 |
| **Suspicious Amount** | Round numbers, just-under limits | 0.15 |
| **Geo Velocity** | Impossible travel between txns | 0.25 |

**Risk Scoring**: 0.0–1.0 → `LOW` | `MEDIUM` | `HIGH` | `CRITICAL`
- Auto-block on CRITICAL
- Manual review queue for HIGH
- Webhook notifications for compliance team

### 📊 Observability
- Structured JSON logging with correlation IDs
- Request/response latency histograms
- Prometheus metrics (`/metrics`)
- Health checks (`/health`, `/health/ready`, `/health/live`)
- OpenAPI/Swagger documentation (`/docs`)

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|------------|
| **API Framework** | FastAPI 0.110+ |
| **Language** | Python 3.11+ |
| **ORM** | SQLAlchemy 2.0 (async) |
| **Migrations** | Alembic |
| **Database** | PostgreSQL 16+ |
| **Cache/Queue** | Redis 7+ / Celery |
| **Auth** | python-jose, passlib[argon2] |
| **Validation** | Pydantic v2 |
| **Testing** | Pytest, pytest-asyncio, httpx |
| **Observability** | structlog, prometheus-client |
| **Containerization** | Docker, Docker Compose |
| **Documentation** | OpenAPI 3.1, Scalar/Redoc |

---

## 📁 Project Structure

```
FinLedger/
├── architecture/
│   ├── diagrams/           # Mermaid diagrams
│   └── docs/               # Architecture decision records
├── docker/
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── docker-compose.prod.yml
├── scripts/
│   ├── init_db.py
│   ├── seed_data.py
│   └── run_migrations.py
├── src/
│   ├── api/
│   │   ├── config/         # Settings, environment
│   │   ├── dependencies/   # FastAPI dependencies (DB, auth, etc.)
│   │   ├── middleware/     # RequestID, logging, rate limiting
│   │   ├── models/         # Pydantic request/response models
│   │   ├── routes/         # API route handlers
│   │   ├── schemas/        # OpenAPI schemas
│   │   ├── services/       # Business logic layer
│   │   ├── repositories/   # Data access layer
│   │   └── utils/          # Helpers, exceptions
│   ├── core/
│   │   ├── auth/           # JWT, RBAC, password hashing
│   │   ├── fraud/          # Fraud rules, risk scoring
│   │   ├── ledger/         # Double-entry accounting engine
│   │   ├── transaction/    # Transaction processing
│   │   └── wallet/         # Wallet operations
│   └── db/
│       ├── models/         # SQLAlchemy ORM models
│       ├── repositories/   # Repository implementations
│       └── migrations/     # Alembic migrations
└── tests/
    ├── unit/
    ├── integration/
    └── fixtures/
```

---

## 🚀 Quick Start

### Prerequisites
- Docker & Docker Compose
- Python 3.11+ (for local development)
- Make (optional, for convenience commands)

### Development Setup

```bash
# Clone and navigate
cd FinLedger

# Start all services (PostgreSQL, Redis, API)
docker compose -f docker/docker-compose.yml up -d

# Run database migrations
docker compose -f docker/docker-compose.yml exec api alembic upgrade head

# Seed development data
docker compose -f docker/docker-compose.yml exec api python scripts/seed_data.py

# API available at http://localhost:8000
# Swagger docs at http://localhost:8000/docs
# Metrics at http://localhost:8000/metrics
```

### Local Development (without Docker)

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Set environment variables
cp .env.example .env
# Edit .env with your database/redis URLs

# Run migrations
alembic upgrade head

# Start development server
uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000
```

---

## 📚 API Documentation

### Authentication
```bash
# Register
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "SecurePass123!", "full_name": "John Doe"}'

# Login
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "SecurePass123!"}'

# Response includes access_token and refresh_token
```

### Wallet Operations
```bash
# Create wallet (requires auth)
curl -X POST http://localhost:8000/api/v1/wallets \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"currency": "USD", "name": "Primary Wallet"}'

# Get balance
curl -X GET http://localhost:8000/api/v1/wallets/{wallet_id}/balance \
  -H "Authorization: Bearer <access_token>"

# Deposit
curl -X POST http://localhost:8000/api/v1/wallets/{wallet_id}/deposit \
  -H "Authorization: Bearer <access_token>" \
  -H "Idempotency-Key: unique-key-123" \
  -H "Content-Type: application/json" \
  -d '{"amount": "100.00", "description": "Salary deposit"}'

# Transfer
curl -X POST http://localhost:8000/api/v1/wallets/{wallet_id}/transfer \
  -H "Authorization: Bearer <access_token>" \
  -H "Idempotency-Key: unique-key-456" \
  -H "Content-Type: application/json" \
  -d '{"amount": "50.00", "destination_wallet_id": "wallet-uuid", "description": "Payment"}'
```

### Ledger Queries
```bash
# List transactions with filters
curl -X GET "http://localhost:8000/api/v1/ledger/transactions?wallet_id=xxx&limit=20&offset=0" \
  -H "Authorization: Bearer <access_token>"

# Get account balance at point in time
curl -X GET "http://localhost:8000/api/v1/ledger/accounts/{account_id}/balance?as_of=2024-01-15T10:00:00Z" \
  -H "Authorization: Bearer <access_token>"
```

### Fraud Events
```bash
# Get fraud events (compliance role required)
curl -X GET http://localhost:8000/api/v1/fraud/events?risk_level=HIGH \
  -H "Authorization: Bearer <admin_token>"
```

---

## 🧪 Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific test categories
pytest tests/unit/
pytest tests/integration/

# Run with specific markers
pytest -m "not slow"
```

---

## 📈 Monitoring & Observability

### Health Checks
| Endpoint | Purpose |
|----------|---------|
| `GET /health` | Basic liveness |
| `GET /health/ready` | Readiness (DB, Redis connected) |
| `GET /health/live` | Liveness probe |

### Metrics (Prometheus)
- `http_requests_total` — Request counter by method, path, status
- `http_request_duration_seconds` — Latency histogram
- `wallet_balance` — Current wallet balances
- `transaction_total` — Transaction counter by type
- `fraud_risk_score` — Risk score distribution
- `ledger_entry_total` — Ledger entries created

### Structured Logging
All logs include: `request_id`, `user_id`, `timestamp`, `level`, `message`, `context`

```json
{
  "timestamp": "2024-01-15T10:30:45.123Z",
  "level": "INFO",
  "request_id": "req_abc123",
  "user_id": "user_xyz789",
  "message": "Transfer completed",
  "context": {
    "source_wallet": "wallet_1",
    "dest_wallet": "wallet_2",
    "amount": "50.00",
    "transaction_id": "txn_456"
  }
}
```

---

## 🐳 Deployment

### Docker Compose (Production)
```bash
docker compose -f docker/docker-compose.prod.yml up -d
```

### Kubernetes (Helm chart available in `deploy/helm/`)

Key production considerations:
- PostgreSQL: Primary + read replicas, connection pooling (PgBouncer)
- Redis: Cluster mode for HA
- API: Horizontal pod autoscaling based on CPU/custom metrics
- TLS termination at ingress
- Secrets via Vault/SealedSecrets

---

## 🎓 Learning Outcomes

This project demonstrates proficiency in:

| Area | Implementation |
|------|----------------|
| **Backend Architecture** | Clean architecture, dependency inversion, domain-driven design |
| **Financial Systems** | Double-entry accounting, balance types, reconciliation |
| **API Design** | RESTful, idempotency, pagination, filtering, versioning |
| **Security** | JWT, RBAC, rate limiting, input validation, secure defaults |
| **Database** | Complex migrations, indexing, locking strategies, ACID |
| **Concurrency** | Optimistic locking, row-level locks, distributed locks |
| **Observability** | Structured logging, metrics, tracing, health checks |
| **Testing** | Unit, integration, property-based, contract testing |
| **DevOps** | Docker, CI/CD, migrations, zero-downtime deployments |

---

## 📋 Roadmap

### Phase 1: Core MVP (3–4 hours) ✅
- [x] Project structure & configuration
- [x] Authentication (JWT + Refresh + RBAC)
- [x] User & Wallet CRUD
- [x] Double-entry ledger engine
- [x] Deposit/Withdraw/Transfer
- [x] Basic fraud rules
- [x] Docker + health checks
- [x] OpenAPI docs

### Phase 2: Production Features (Week 2) ✅
- [x] Webhook system for async events
- [x] Admin dashboard APIs
- [x] Advanced fraud rules (ML-ready)
- [x] Reconciliation engine
- [x] Audit log immutability proofs
- [x] Multi-tenancy support
- [x] CI/CD pipeline (GitHub Actions)
- [x] Load testing scripts

### Phase 3: Advanced FinTech (Week 3+) 🚧
- [ ] Multi-rail payment orchestration (ACH, Wire, RTP)
- [ ] Stablecoin integration (USDC, USDT)
- [ ] Card issuing virtual accounts
- [ ] Regulatory reporting (SAR, CTR)
- [ ] Real-time streaming (Kafka/Redpanda)
- [ ] Distributed tracing (OpenTelemetry)
- [ ] Chaos engineering experiments
- [ ] Performance benchmarks

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

## 🙏 Acknowledgments

Architecture inspired by:
- **Formance Ledger** — Programmable core ledger design
- **Modern Treasury** — Ledger-first PSP architecture
- **Apache Fineract** — Modular banking platform
- **Kill Bill** — Subscription billing & payments
- **Stripe/Wise/Monzo Engineering Blogs** — Production practices

---

## 📞 Contact

**Built by a Principal Software Engineer** targeting:
LSEG • Goldman Sachs • JP Morgan • Morgan Stanley • Bloomberg • Visa • Mastercard • Stripe • PayPal • Razorpay

*This project showcases production-grade backend engineering for financial systems. Not a clone — an original implementation demonstrating deep understanding of fintech architecture patterns.*