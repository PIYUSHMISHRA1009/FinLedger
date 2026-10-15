# FinLedger

A digital wallet and transaction platform built with FastAPI and PostgreSQL, featuring a double-entry ledger, wallet management, fraud detection, authentication, and monitoring.

## Project Overview

FinLedger demonstrates the following backend capabilities:

- Immutable double-entry ledger
- Multi-currency digital wallets
- Rule-based fraud detection and risk scoring
- JWT authentication and role-based access control
- Layered backend architecture
- Structured logging, metrics, and health checks

## Architecture

```text
Client
  |
FastAPI API
  |
Middleware
(Authentication, Rate Limiting, Logging, Request IDs)
  |
Routes
  |
Services (Business Logic)
  |
Repositories (Data Access)
  |
PostgreSQL / Redis

Core Domains:
- Ledger
- Wallet
- Transaction Processing
- Fraud Detection
- Authentication
```

## Features

### Authentication and Authorization

- User registration with email verification
- JWT access tokens and refresh tokens
- Role-based access control (USER, ADMIN, COMPLIANCE)
- Argon2id password hashing
- Rate limiting by IP and user
- Idempotent API endpoints

### Wallet Management

- Multi-currency wallet creation
- Posted, pending, and available balances
- Deposit, withdrawal, and transfer operations
- Balance reconciliation
- Wallet locking for concurrent operations

### Double-Entry Ledger

- Append-only transaction history
- Chart of accounts supporting assets, liabilities, equity, revenue, and expenses
- Balanced debit and credit entries for every transaction
- Debit-normal and credit-normal account handling
- Optimistic locking through transaction versioning
- Point-in-time balance queries

### Fraud Detection

| Rule | Description | Risk Weight |
|---|---|---:|
| Large Transaction | Amount exceeds the 95th percentile | 0.35 |
| Velocity Check | More than 10 transactions per minute or 50 per hour | 0.30 |
| Frequent Transfers | More than 5 transfers to the same counterparty per day | 0.20 |
| Suspicious Amount | Round numbers or amounts just below limits | 0.15 |
| Geo Velocity | Impossible travel between transactions | 0.25 |

Risk scores range from `0.0` to `1.0` and are classified as `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL`.

- Automatic blocking for critical-risk transactions
- Manual review queue for high-risk transactions
- Webhook notifications for the compliance team

### Observability

- Structured JSON logging with correlation IDs
- Request and response latency histograms
- Prometheus metrics at `/metrics`
- Health checks at `/health`, `/health/ready`, and `/health/live`
- OpenAPI documentation at `/docs`

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| API Framework | FastAPI |
| ORM | SQLAlchemy 2.0 (async) |
| Migrations | Alembic |
| Database | PostgreSQL 16+ |
| Cache and Queue | Redis 7+ / Celery |
| Authentication | python-jose, passlib[argon2] |
| Validation | Pydantic v2 |
| Testing | Pytest, pytest-asyncio, httpx |
| Observability | structlog, prometheus-client |
| Containerization | Docker, Docker Compose |
| API Documentation | OpenAPI 3.1, Scalar/Redoc |

## Project Structure

```text
FinLedger/
├── architecture/
│   ├── diagrams/
│   └── docs/
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
│   │   ├── config/
│   │   ├── dependencies/
│   │   ├── middleware/
│   │   ├── models/
│   │   ├── routes/
│   │   ├── schemas/
│   │   ├── services/
│   │   ├── repositories/
│   │   └── utils/
│   ├── core/
│   │   ├── auth/
│   │   ├── fraud/
│   │   ├── ledger/
│   │   ├── transaction/
│   │   └── wallet/
│   └── db/
│       ├── models/
│       ├── repositories/
│       └── migrations/
└── tests/
    ├── unit/
    ├── integration/
    └── fixtures/
```

## Getting Started

### Prerequisites

- Docker and Docker Compose
- Python 3.11+ for local development

### Run with Docker Compose

```bash
# Start PostgreSQL, Redis, and the API
docker compose -f docker/docker-compose.yml up -d

# Run database migrations
docker compose -f docker/docker-compose.yml exec api alembic upgrade head

# Seed development data
docker compose -f docker/docker-compose.yml exec api python scripts/seed_data.py
```

The API is available at `http://localhost:8000`.

- Swagger documentation: `http://localhost:8000/docs`
- Metrics: `http://localhost:8000/metrics`

### Run Locally

```bash
# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Configure environment variables
cp .env.example .env
# Edit .env with your database and Redis URLs

# Run migrations
alembic upgrade head

# Start the development server
uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000
```

## API Examples

### Authentication

Register a user:

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"SecurePass123!","full_name":"John Doe"}'
```

Log in:

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"SecurePass123!"}'
```

The response includes access and refresh tokens.

### Wallet Operations

Create a wallet:

```bash
curl -X POST http://localhost:8000/api/v1/wallets \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"currency":"USD","name":"Primary Wallet"}'
```

Get a wallet balance:

```bash
curl -X GET http://localhost:8000/api/v1/wallets/<wallet_id>/balance \
  -H "Authorization: Bearer <access_token>"
```

Deposit funds:

```bash
curl -X POST http://localhost:8000/api/v1/wallets/<wallet_id>/deposit \
  -H "Authorization: Bearer <access_token>" \
  -H "Idempotency-Key: unique-key-123" \
  -H "Content-Type: application/json" \
  -d '{"amount":"100.00","description":"Salary deposit"}'
```

Transfer funds:

```bash
curl -X POST http://localhost:8000/api/v1/wallets/<wallet_id>/transfer \
  -H "Authorization: Bearer <access_token>" \
  -H "Idempotency-Key: unique-key-456" \
  -H "Content-Type: application/json" \
  -d '{"amount":"50.00","destination_wallet_id":"<wallet_id>","description":"Payment"}'
```

### Ledger Queries

List transactions:

```bash
curl -X GET "http://localhost:8000/api/v1/ledger/transactions?wallet_id=<wallet_id>&limit=20&offset=0" \
  -H "Authorization: Bearer <access_token>"
```

Get an account balance at a point in time:

```bash
curl -X GET "http://localhost:8000/api/v1/ledger/accounts/<account_id>/balance?as_of=2024-01-15T10:00:00Z" \
  -H "Authorization: Bearer <access_token>"
```

### Fraud Events

Retrieve fraud events (requires the appropriate compliance role):

```bash
curl -X GET "http://localhost:8000/api/v1/fraud/events?risk_level=HIGH" \
  -H "Authorization: Bearer <admin_token>"
```

## Testing

```bash
# Run all tests
pytest

# Run tests with coverage
pytest --cov=src --cov-report=html

# Run unit and integration tests
pytest tests/unit/
pytest tests/integration/

# Skip slow tests
pytest -m "not slow"
```

## Monitoring

### Health Checks

| Endpoint | Purpose |
|---|---|
| `GET /health` | Basic health check |
| `GET /health/ready` | Readiness check, including database and Redis connections |
| `GET /health/live` | Liveness check |

### Prometheus Metrics

- `http_requests_total` — Request count by method, path, and status
- `http_request_duration_seconds` — Request latency histogram
- `wallet_balance` — Current wallet balances
- `transaction_total` — Transaction count by type
- `fraud_risk_score` — Risk score distribution
- `ledger_entry_total` — Ledger entries created

### Structured Logs

Logs include the request ID, user ID, timestamp, log level, message, and context.

Example:

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

## Deployment

The project includes Docker Compose configurations for deployment:

```bash
docker compose -f docker/docker-compose.prod.yml up -d
```

The original README also references a Helm chart under `deploy/helm/`.

Deployment considerations include:

- PostgreSQL primary and read replicas with connection pooling
- Redis cluster configuration for high availability
- Horizontal API scaling
- TLS termination at ingress
- Secret management using tools such as Vault or Sealed Secrets

## Future Work

Planned features include:

- Multi-rail payment orchestration (ACH, Wire, RTP)
- Stablecoin integration (USDC, USDT)
- Virtual card issuing
- Regulatory reporting (SAR, CTR)
- Real-time streaming with Kafka or Redpanda
- Distributed tracing with OpenTelemetry
- Chaos engineering experiments
- Performance benchmarks

## Contributing

1. Fork the repository.
2. Create a feature branch.
3. Commit your changes.
4. Push the branch.
5. Open a pull request.

## License

MIT License. See the `LICENSE` file for details.
