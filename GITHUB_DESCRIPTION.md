# FinLedger

> **A production-grade digital wallet and transaction platform with an immutable double-entry ledger, fraud detection engine, and financial transaction processing — built to showcase backend engineering excellence for top fintech companies.**

## 🎯 Overview

FinLedger is an original, production-ready fintech backend platform demonstrating deep expertise in financial systems engineering. It implements a complete double-entry accounting ledger, multi-currency digital wallets, real-time fraud detection, and secure authentication — all following clean architecture principles.

## ✨ Key Features

- **🔐 Double-Entry Ledger** — Immutable, ACID-compliant financial records with chart of accounts (25 accounts), three balance types (Posted/Pending/Available), and materialized views for O(1) reads
- **💰 Digital Wallets** — Multi-currency support with deposit, withdrawal, and wallet-to-wallet transfers
- **🛡️ Fraud Detection Engine** — 10 configurable rules (velocity, amount thresholds, counterparty frequency, geo-velocity, suspicious patterns) with weighted risk scoring (0.0-1.0) and review queues
- **🔐 Secure Authentication** — JWT RS256 (15min access / 7d refresh), Argon2id password hashing, refresh token rotation with reuse detection, RBAC (USER/ADMIN/COMPLIANCE/SYSTEM)
- **📋 Exactly-Once Semantics** — Idempotency keys on all mutations with 24hr cache and conflict detection
- **📊 Observability** — Structured JSON logging, Prometheus metrics, health checks, OpenTelemetry tracing
- **🧪 Testing** — Unit + integration tests with fixtures, 80%+ coverage target

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  CLEAN ARCHITECTURE                                             │
│  Routes → Services → Repositories → Database                   │
├─────────────────────────────────────────────────────────────────┤
│  CORE DOMAINS                                                   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐ │
│  │  LEDGER  │ │  WALLET  │ │FRAUD ENG │ │  AUTH    │ │TXN MGR │ │
│  │Double-   │ │Multi-    │ │Rule-based│ │JWT+RBAC  │ │Idempot.│ │
│  │Entry Acct│ │Currency  │ │Scoring   │ │Argon2id  │ │State   │ │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

## 🛠️ Tech Stack

| Layer | Technology |
|-------|------------|
| **API** | FastAPI 0.110+, Python 3.11+ |
| **Database** | PostgreSQL 16, SQLAlchemy 2.0 (async), Alembic |
| **Cache/Queue** | Redis 7, Celery |
| **Auth** | JWT RS256, Argon2id, python-jose |
| **Validation** | Pydantic v2 |
| **Testing** | Pytest, pytest-asyncio, httpx |
| **Observability** | Prometheus, Grafana, Loki, Tempo |
| **Containerization** | Docker, Docker Compose |
| **CI/CD** | GitHub Actions, Terraform, ArgoCD |

## 📚 Documentation

| Document | Description |
|----------|-------------|
| [System Architecture](architecture/docs/system_architecture.md) | C4 diagrams, 7 ADRs, NFRs |
| [Database Schema](architecture/docs/database_schema.md) | ER diagram + full PostgreSQL SQL |
| [API Documentation](architecture/docs/api_documentation.md) | OpenAPI 3.1 spec |
| [Authentication Flow](architecture/docs/authentication_flow.md) | JWT, refresh, RBAC |
| [Transaction Lifecycle](architecture/docs/transaction_lifecycle.md) | State machine, idempotency |
| [Fraud Engine](architecture/docs/fraud_engine.md) | 10 rules, velocity, scoring |
| [Double-Entry Ledger](architecture/docs/double_entry_ledger.md) | Chart of accounts, examples |
| [Deployment](architecture/docs/deployment_architecture.md) | EKS, Terraform, K8s, CI/CD |

## 🚀 Quick Start

```bash
# Prerequisites: Docker, Docker Compose
git clone <repo-url>
cd FinLedger

# Start all services (PostgreSQL, Redis, API, Celery, Prometheus, Grafana)
docker compose -f docker/docker-compose.yml up -d

# Initialize database
docker compose -f docker/docker-compose.yml exec api python scripts/init_db.py

# Seed development data
docker compose -f docker/docker-compose.yml exec api python scripts/seed_data.py

# API: http://localhost:8000
# Swagger Docs: http://localhost:8000/docs
# Metrics: http://localhost:8000/metrics
# Grafana: http://localhost:3000 (admin/admin)
```

## 🎯 Target Audience

This project demonstrates production-grade backend engineering skills for roles at:
- **Exchanges & Market Infrastructure**: LSEG
- **Investment Banks**: Goldman Sachs, JP Morgan, Morgan Stanley
- **Financial Data**: Bloomberg
- **Payment Networks**: Visa, Mastercard
- **FinTech**: Stripe, PayPal, Razorpay

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

*Built by a Principal Software Engineer targeting top-tier financial technology roles. Not a clone — an original implementation demonstrating deep fintech architecture expertise.*