# FinLedger — AI Agent Guide

## Purpose
FinLedger is a production-style fintech platform built around immutable double-entry accounting, multi-currency wallets, transaction processing, fraud detection, authentication/RBAC, observability, and analytics. The repository is intentionally structured to demonstrate backend engineering and quantitative/data-analysis skills.

## Repository map
- `src/finledger/api/` — FastAPI application, routes, schemas, dependencies, middleware.
- `src/finledger/core/` — domain services: auth, wallet, ledger, transaction, fraud, reconciliation, webhooks.
- `src/finledger/db/` — SQLAlchemy models, repositories, database integration and migrations.
- `src/finledger/analytics/` — analytical and time-series forecasting functionality.
- `tests/unit/` — isolated service/domain tests.
- `tests/integration/` — API/database integration tests.
- `architecture/` — architecture documentation and design decisions.
- `scripts/` — database setup and development utilities.
- `docker/` — container/deployment configuration.

## Core invariants
1. Never mutate or bypass the immutable double-entry ledger semantics.
2. Financial amounts use decimal/precise database numeric types; do not introduce floating-point arithmetic into ledger calculations.
3. Preserve idempotency, optimistic-locking/concurrency behavior, authorization and auditability.
4. Keep business logic in services rather than embedding it in route handlers.
5. Reuse existing SQLAlchemy repositories/models and async database patterns before adding new data-access paths.
6. Do not expose secrets, credentials, raw authentication tokens, or unnecessary PII in logs or documentation.

## Forecasting module
`src/finledger/analytics/forecasting.py` provides a separate analytical layer over aggregated daily observations. It does not alter ledger semantics.

The implementation is deliberately aligned with the project's Time Series Analysis coursework:
- stationarity and the Augmented Dickey-Fuller test;
- ARIMA;
- SARIMA with weekly seasonality;
- exponential smoothing / ETS;
- chronological holdout evaluation using MAE, RMSE and MAPE;
- a comparison function for selecting a model using out-of-sample error.

The primary transaction series can be derived from `Transaction.created_at` and `Transaction.amount`. The transaction model already contains timestamped monetary observations and indexed `created_at`, so analytics should aggregate from those fields rather than creating a duplicate transaction store.

Do not claim a model is accurate without a real holdout evaluation. Do not call synthetic/seed data a real-world forecast. Forecast outputs are analytical estimates, not financial advice.

## Expected development workflow
1. Inspect existing models/routes/services before creating new abstractions.
2. Make the smallest coherent change that satisfies the requirement.
3. Add/modify tests for new behavior.
4. Run the relevant unit/integration tests and formatting/type checks where available.
5. Update documentation and API examples when public behavior changes.
6. Preserve backward compatibility unless a breaking change is explicitly requested.

## Forecasting implementation guidance
For a transaction forecasting feature:
1. Query completed/posted transactions with a bounded date range.
2. Aggregate by day and currency; never combine currencies without an explicit conversion methodology.
3. Validate missing/insufficient observations.
4. Run stationarity diagnostics before choosing differencing/model configuration.
5. Establish a simple baseline before ARIMA/SARIMA/ETS.
6. Use chronological train/validation/test splits; never random-shuffle time-series observations.
7. Compare candidate models using out-of-sample metrics.
8. Return forecast timestamps, point estimates, model name/version, training window, horizon and evaluation metrics.
9. Add confidence/prediction intervals when the chosen statsmodels result supports them.

## Important commands
```bash
pytest
pytest --cov=src --cov-report=html
ruff check .
mypy src
```

## Agent safety rules
- Do not rewrite large parts of the architecture when a focused change is sufficient.
- Do not delete tests merely to make a build pass.
- Do not silently change API contracts.
- Do not fabricate transaction history, model metrics, or business impact for documentation/resume claims.
- When an implementation depends on a missing external dataset, document the dependency and provide a reproducible ingestion interface rather than inventing production data.
