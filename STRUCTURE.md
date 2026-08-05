# FinLedger - Project Structure Overview

```
FinLedger/
├── .github/
│   └── workflows/
│       └── ci-cd.yml              # GitHub Actions CI/CD pipeline
├── alembic/
│   ├── env.py                     # Alembic environment config
│   ├── script.py.mako             # Migration template
│   └── versions/
│       └── 001_initial.py         # Initial migration with seed data
├── docker/
│   ├── Dockerfile                 # Multi-stage Docker build
│   ├── docker-compose.yml         # Development stack
│   ├── prometheus.yml             # Prometheus config
│   └── grafana/
│       ├── datasources/
│       │   └── datasources.yml    # Grafana datasource config
│       └── dashboards/            # Dashboard JSON files (to be added)
├── scripts/
│   ├── init_db.py                 # Database initialization
│   └── seed_data.py               # Development data seeding
├── src/
│   └── finledger/
│       ├── __init__.py
│       ├── api/
│       │   ├── __init__.py
│       │   ├── main.py            # FastAPI app factory
│       │   ├── config/
│       │   │   ├── __init__.py
│       │   │   └── settings.py    # Pydantic settings
│       │   ├── routes/
│       │   │   ├── __init__.py
│       │   │   ├── auth.py        # Authentication endpoints
│       │   │   ├── wallets.py     # Wallet CRUD & transactions
│       │   │   ├── ledger.py      # Ledger queries
│       │   │   ├── fraud.py       # Fraud admin endpoints
│       │   │   └── health.py      # Health & metrics
│       │   └── schemas/
│       │       └── __init__.py    # Pydantic request/response models
│       ├── core/
│       │   ├── __init__.py
│       │   ├── auth/
│       │   │   ├── __init__.py
│       │   │   ├── password.py    # Argon2id hashing
│       │   │   ├── tokens.py      # JWT + refresh tokens
│       │   │   └── rbac.py        # Auth service & RBAC
│       │   ├── ledger/
│       │   │   ├── __init__.py
│       │   │   ├── service.py     # Double-entry ledger engine
│       │   │   └── exceptions.py  # Ledger-specific exceptions
│       │   ├── wallet/
│       │   │   ├── __init__.py
│       │   │   └── service.py     # Wallet operations
│       │   ├── fraud/
│       │   │   ├── __init__.py
│       │   │   └── service.py     # Fraud detection engine
│       │   ├── transaction/
│       │   │   ├── __init__.py
│       │   │   └── (future: transaction processing pipeline)
│       │   └── celery_app.py      # Background task config
│       ├── db/
│       │   ├── __init__.py
│       │   ├── database.py        # SQLAlchemy async setup
│       │   └── models/
│       │       └── __init__.py    # All SQLAlchemy ORM models
│       └── exceptions.py          # Base exception classes
├── tests/
│   ├── conftest.py                # Pytest fixtures
│   ├── unit/
│   │   ├── __init__.py
│   │   ├── test_auth.py           # Auth unit tests
│   │   ├── test_ledger.py         # Ledger unit tests
│   │   ├── test_wallet.py         # Wallet unit tests
│   │   └── test_fraud.py          # Fraud unit tests
│   └── integration/
│       ├── __init__.py
│       └── test_api.py            # API integration tests
├── architecture/
│   └── docs/
│       ├── system_architecture.md    # C4 diagrams, ADRs, NFRs
│       ├── database_schema.md        # ER diagram, SQL, indexes
│       ├── api_documentation.md      # OpenAPI 3.1 spec
│       ├── authentication_flow.md    # JWT, refresh, RBAC
│       ├── transaction_lifecycle.md  # State machine, idempotency
│       ├── fraud_engine.md           # Rules, velocity, scoring
│       ├── double_entry_ledger.md    # Chart of accounts, examples
│       ├── deployment_architecture.md # K8s, Terraform, CI/CD
│       ├── resume_bullets_ats.md     # Resume bullets & ATS keywords
│       ├── recruiter_explanation.md  # Why this stands out
│       └── mvp_roadmap.md            # Phase 1-3 roadmap
├── .env.example                   # Environment variables template
├── requirements.txt               # Production dependencies
├── requirements-dev.txt           # Development dependencies
├── pyproject.toml                 # Project config (ruff, mypy, pytest)
├── alembic.ini                    # Alembic configuration
├── PROJECT_INDEX.md               # Project navigation guide
└── README.md                      # Project overview
```

## Key Implementation Files

| Component | File | Description |
|-----------|------|-------------|
| **App Entry** | `src/finledger/api/main.py` | FastAPI factory with middleware, lifespan, exception handlers |
| **Config** | `src/finledger/api/config/settings.py` | Pydantic Settings with validation |
| **Database** | `src/finledger/db/database.py` | Async SQLAlchemy engine & session management |
| **Models** | `src/finledger/db/models/__init__.py` | 11 SQLAlchemy ORM models |
| **Auth** | `src/finledger/core/auth/rbac.py` | AuthService, JWT, RBAC, password hashing |
| **Ledger** | `src/finledger/core/ledger/service.py` | Double-entry engine with materialized balances |
| **Wallet** | `src/finledger/core/wallet/service.py` | CRUD, deposit, withdraw, transfer |
| **Fraud** | `src/finledger/core/fraud/service.py` | Rule engine with 10 rules, velocity tracking |
| **Auth Routes** | `src/finledger/api/routes/auth.py` | Register, login, refresh, logout |
| **Wallet Routes** | `src/finledger/api/routes/wallets.py` | Wallet CRUD, deposit, withdraw, transfer |
| **Ledger Routes** | `src/finledger/api/routes/ledger.py` | Chart of accounts, balances, trial balance |
| **Fraud Routes** | `src/finledger/api/routes/fraud.py` | Admin fraud review, rule management |
| **Health** | `src/finledger/api/routes/health.py` | /health, /health/ready, /metrics |
| **Tests** | `tests/` | Unit + integration tests with fixtures |
| **CI/CD** | `.github/workflows/ci-cd.yml` | Test → Build → Deploy staging → Deploy prod |

## Architecture Documentation

All design documents are in `architecture/docs/`:
- **System Architecture**: C4 diagrams, 7 ADRs, NFRs
- **Database Schema**: Full ER diagram + PostgreSQL SQL with seed data
- **API Documentation**: OpenAPI 3.1 spec with all endpoints
- **Authentication Flow**: JWT RS256, refresh rotation, RBAC
- **Transaction Lifecycle**: State machine, idempotency, concurrency
- **Fraud Engine**: 10 rules, velocity tracking, risk scoring
- **Double-Entry Ledger**: Chart of accounts, 4 transaction examples
- **Deployment**: EKS, Terraform, K8s manifests, CI/CD, monitoring
- **Resume/ATS**: Company-tailored bullets, 200+ keywords
- **Recruiter Guide**: Why this project stands out
- **MVP Roadmap**: Phase 1 (4hrs), Phase 2 (1wk), Phase 3 (2-3wks)