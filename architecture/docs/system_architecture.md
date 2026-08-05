# FinLedger System Architecture

## High-Level Architecture

```mermaid
C4Context
    title FinLedger - System Context Diagram

    Person(customer, "Customer", "End user of the digital wallet")
    Person(admin, "Admin/Compliance", "Internal team managing fraud, compliance")
    System_Boundary(b1, "FinLedger Platform") {
        System(api, "API Gateway", "FastAPI - REST API, Auth, Rate Limiting")
        System(ledger, "Ledger Engine", "Double-entry accounting, immutable records")
        System(wallet, "Wallet Service", "Multi-currency wallets, balance management")
        System(fraud, "Fraud Engine", "Rule-based risk scoring, real-time detection")
        System(auth, "Auth Service", "JWT, RBAC, Token Management")
    }
    System_Ext(db, "PostgreSQL", "Primary data store - ACID, ledger entries")
    System_Ext(redis, "Redis", "Cache, Rate limiting, Celery broker")
    System_Ext(monitoring, "Monitoring Stack", "Prometheus, Grafana, Loki")

    Rel(customer, api, "HTTPS/JSON", "Wallet ops, Transfers, Balance queries")
    Rel(admin, api, "HTTPS/JSON", "Fraud review, Audit logs, Compliance")
    Rel(api, ledger, "Internal gRPC/Function calls", "Create ledger entries")
    Rel(api, wallet, "Internal calls", "Wallet CRUD, Balance updates")
    Rel(api, fraud, "Async/Event-driven", "Transaction risk scoring")
    Rel(api, auth, "Internal calls", "Token validation, RBAC checks")
    Rel(ledger, db, "SQLAlchemy/AsyncPG", "Immutable ledger entries")
    Rel(wallet, db, "SQLAlchemy/AsyncPG", "Wallet & balance state")
    Rel(fraud, db, "SQLAlchemy/AsyncPG", "Fraud events, Rules config")
    Rel(auth, db, "SQLAlchemy/AsyncPG", "Users, Roles, Refresh tokens")
    Rel(api, redis, "Cache/Rate limit", "Rate limiting, Session cache")
    Rel(api, monitoring, "Metrics/Logs", "Prometheus metrics, Structured logs")
```

## Container Diagram

```mermaid
C4Container
    title FinLedger - Container Diagram

    Container_Boundary(api_boundary, "API Layer") {
        Container(routes, "Route Handlers", "FastAPI", "REST endpoints, Request validation")
        Container(middleware, "Middleware Stack", "Starlette", "Auth, RateLimit, Logging, RequestID")
        Container(deps, "Dependencies", "FastAPI Depends", "DB sessions, Auth, Pagination")
    }

    Container_Boundary(service_boundary, "Service Layer (Business Logic)") {
        Container(auth_svc, "Auth Service", "Python", "JWT, Refresh tokens, RBAC, Password hashing")
        Container(wallet_svc, "Wallet Service", "Python", "Wallet CRUD, Deposit, Withdraw, Transfer")
        Container(ledger_svc, "Ledger Service", "Python", "Double-entry, Chart of accounts, Reconciliation")
        Container(txn_svc, "Transaction Service", "Python", "Processing pipeline, Idempotency, State machine")
        Container(fraud_svc, "Fraud Service", "Python", "Rule engine, Risk scoring, Event emission")
    }

    Container_Boundary(repo_boundary, "Repository Layer (Data Access)") {
        Container(user_repo, "User Repository", "SQLAlchemy", "User, Role, Refresh token queries")
        Container(wallet_repo, "Wallet Repository", "SQLAlchemy", "Wallet, Balance queries with locking")
        Container(ledger_repo, "Ledger Repository", "SQLAlchemy", "Entries, Accounts, Balances, Versions")
        Container(txn_repo, "Transaction Repository", "SQLAlchemy", "Transaction state, Idempotency keys")
        Container(fraud_repo, "Fraud Repository", "SQLAlchemy", "Events, Rules, Risk scores")
    }

    ContainerDb(db, "PostgreSQL 16+", "AsyncPG", "ACID, MVCC, Row-level locks, Partitioning")
    ContainerDb(redis, "Redis 7+", "asyncio-redis", "Cache, Rate limits, Celery broker, Distributed locks")

    Rel(routes, middleware, "Wraps")
    Rel(routes, deps, "Injects")
    Rel(routes, auth_svc, "Calls")
    Rel(routes, wallet_svc, "Calls")
    Rel(routes, ledger_svc, "Calls")
    Rel(routes, txn_svc, "Calls")
    Rel(routes, fraud_svc, "Calls (async)")

    Rel(auth_svc, user_repo, "Uses")
    Rel(wallet_svc, wallet_repo, "Uses")
    Rel(wallet_svc, ledger_repo, "Uses (for entries)")
    Rel(ledger_svc, ledger_repo, "Uses")
    Rel(txn_svc, txn_repo, "Uses")
    Rel(txn_svc, wallet_repo, "Uses")
    Rel(txn_svc, ledger_repo, "Uses")
    Rel(txn_svc, fraud_svc, "Emits events to")
    Rel(fraud_svc, fraud_repo, "Uses")

    Rel(user_repo, db, "SQLAlchemy/Async")
    Rel(wallet_repo, db, "SQLAlchemy/Async")
    Rel(ledger_repo, db, "SQLAlchemy/Async")
    Rel(txn_repo, db, "SQLAlchemy/Async")
    Rel(fraud_repo, db, "SQLAlchemy/Async")

    Rel(middleware, redis, "Rate limit checks")
    Rel(auth_svc, redis, "Token blacklist cache")
    Rel(wallet_svc, redis, "Balance cache (optional)")
```

## Component Diagram - Ledger Engine

```mermaid
C4Component
    title FinLedger - Ledger Engine Components

    Component(chart_of_accounts, "ChartOfAccounts", "Python Class", "Account definitions, types, normality")
    Component(entry_builder, "EntryBuilder", "Python Class", "Creates balanced debit/credit entries")
    Component(validator, "LedgerValidator", "Python Class", "Validates balance, normality, versioning")
    Component(balancer, "BalanceCalculator", "Python Class", "Posted/Pending/Available balance computation")
    Component(reconciler, "ReconciliationEngine", "Python Class", "Matches ledger to external statements")
    Component(versioning, "OptimisticLocking", "Python Class", "Transaction versioning for concurrency")

    ComponentDb(accounts_table, "ledger_accounts", "PostgreSQL Table", "Account definitions, types, normality")
    ComponentDb(entries_table, "ledger_entries", "PostgreSQL Table", "Immutable debit/credit entries")
    ComponentDb(transactions_table, "ledger_transactions", "PostgreSQL Table", "Transaction headers, metadata, versions")
    ComponentDb(balances_table, "account_balances", "PostgreSQL Table", "Materialized balance views (cached)")

    Rel(entry_builder, chart_of_accounts, "Validates accounts exist")
    Rel(entry_builder, validator, "Validates entries")
    Rel(validator, balancer, "Updates balances after commit")
    Rel(validator, versioning, "Checks version before commit")
    Rel(balancer, accounts_table, "Reads account definitions")
    Rel(balancer, entries_table, "Aggregates entries for balances")
    Rel(balancer, balances_table, "Writes materialized balances")
    Rel(entry_builder, entries_table, "Inserts entries (batch)")
    Rel(entry_builder, transactions_table, "Inserts transaction header")
    Rel(reconciler, entries_table, "Reads for matching")
    Rel(reconciler, balances_table, "Compares materialized vs computed")
```

## Component Diagram - Fraud Engine

```mermaid
C4Component
    title FinLedger - Fraud Detection Engine Components

    Component(rule_engine, "RuleEngine", "Python Class", "Executes rules, computes risk scores")
    Component(velocity_tracker, "VelocityTracker", "Python Class", "Sliding window counters per user/wallet")
    Component(rule_registry, "RuleRegistry", "Python Class", "Dynamic rule registration, configuration")
    Component(risk_scorer, "RiskScorer", "Python Class", "Weighted scoring, threshold classification")
    Component(event_emitter, "FraudEventEmitter", "Python Class", "Emits events for HIGH/CRITICAL risks")
    Component(review_queue, "ReviewQueue", "Python Class", "Manual review workflow for compliance")

    ComponentDb(fraud_events, "fraud_events", "PostgreSQL Table", "Risk scores, triggered rules, decisions")
    ComponentDb(fraud_rules, "fraud_rules", "PostgreSQL Table", "Rule definitions, weights, thresholds")
    ComponentDb(velocity_counters, "velocity_counters", "Redis Sorted Sets", "Real-time velocity tracking")

    Rel(rule_engine, rule_registry, "Gets active rules")
    Rel(rule_engine, velocity_tracker, "Checks velocity limits")
    Rel(rule_engine, risk_scorer, "Computes final score")
    Rel(risk_scorer, event_emitter, "Emits if > threshold")
    Rel(event_emitter, review_queue, "Queues for manual review")
    Rel(rule_engine, fraud_events, "Persists fraud event")
    Rel(rule_registry, fraud_rules, "Loads rule config")
    Rel(velocity_tracker, velocity_counters, "Increments/checks counters")
```

## Sequence Diagram - Transfer Flow

```mermaid
sequenceDiagram
    autonumber
    actor Client
    participant API as API Gateway
    participant Auth as Auth Middleware
    participant TxnSvc as Transaction Service
    participant WalletSvc as Wallet Service
    participant LedgerSvc as Ledger Service
    participant FraudSvc as Fraud Service
    participant DB as PostgreSQL
    participant Redis as Redis

    Client->>API: POST /wallets/{id}/transfer\n{amount, dest_wallet, idempotency_key}
    API->>Auth: Validate JWT, extract user_id
    Auth-->>API: User context + permissions
    API->>Redis: Check idempotency key
    alt Key exists
        Redis-->>API: Return cached response
        API-->>Client: 200 OK (cached)
    else New request
        API->>TxnSvc: Create transaction record (PENDING)
        TxnSvc->>DB: INSERT transaction (idempotency_key, status=PENDING)
        TxnSvc->>WalletSvc: Lock source wallet (SELECT FOR UPDATE)
        WalletSvc->>DB: SELECT * FROM wallets WHERE id=? FOR UPDATE
        WalletSvc->>WalletSvc: Validate balance (Available >= amount)
        alt Insufficient funds
            TxnSvc->>DB: UPDATE transaction SET status=FAILED
            TxnSvc-->>API: Error response
            API-->>Client: 400 Insufficient funds
        else Sufficient funds
            TxnSvc->>FraudSvc: Evaluate risk (async, fire-and-forget)
            FraudSvc->>Redis: Check velocity counters
            FraudSvc->>DB: Load fraud rules
            FraudSvc->>FraudSvc: Compute risk score
            FraudSvc->>DB: INSERT fraud_event
            alt CRITICAL risk
                FraudSvc->>TxnSvc: Block transaction (callback)
                TxnSvc->>DB: UPDATE transaction SET status=BLOCKED
            end
            TxnSvc->>LedgerSvc: Create ledger entries (debit source, credit dest)
            LedgerSvc->>DB: BEGIN TRANSACTION
            LedgerSvc->>DB: INSERT ledger_entries (2 rows, balanced)
            LedgerSvc->>DB: UPDATE account_balances (materialized)
            LedgerSvc->>DB: UPDATE wallets (pending/available balances)
            LedgerSvc->>DB: COMMIT
            TxnSvc->>DB: UPDATE transaction SET status=COMPLETED
            TxnSvc->>Redis: Cache idempotency response
            TxnSvc-->>API: Success response
            API-->>Client: 201 Created {transaction_id, status}
        end
    end
```

## Sequence Diagram - Fraud Detection

```mermaid
sequenceDiagram
    autonumber
    participant TxnSvc as Transaction Service
    participant FraudSvc as Fraud Service
    participant Redis as Redis (Velocity)
    participant DB as PostgreSQL
    participant Queue as Review Queue

    TxnSvc->>FraudSvc: evaluate(transaction_context)
    FraudSvc->>Redis: ZINCRBY velocity:user:{id} 1
    FraudSvc->>Redis: ZRANGE velocity:user:{id} -60s
    FraudSvc->>Redis: ZRANGE velocity:wallet:{id} -1h
    FraudSvc->>DB: SELECT * FROM fraud_rules WHERE active=true
    FraudSvc->>FraudSvc: Rule: Large Transaction (> P95)
    FraudSvc->>FraudSvc: Rule: Velocity (> 10/min)
    FraudSvc->>FraudSvc: Rule: Frequent Counterparty (> 5/day)
    FraudSvc->>FraudSvc: Rule: Suspicious Amount (round, < limit)
    FraudSvc->>FraudSvc: Rule: Geo Velocity (impossible travel)
    FraudSvc->>FraudSvc: risk_score = Σ(rule_weight * triggered)
    FraudSvc->>FraudSvc: risk_level = classify(risk_score)
    FraudSvc->>DB: INSERT INTO fraud_events (txn_id, score, level, rules)
    alt risk_level >= HIGH
        FraudSvc->>Queue: PUSH review_task {txn_id, risk_level, evidence}
        FraudSvc->>TxnSvc: Callback flag (if CRITICAL: block)
    end
    FraudSvc-->>TxnSvc: {risk_score, risk_level, triggered_rules}
```

## Data Flow Diagram

```mermaid
flowchart TD
    subgraph "Ingress"
        A[Client Request] --> B[API Gateway\nRate Limit / Auth]
    end

    subgraph "Processing"
        B --> C{Route}
        C -->|Auth| D[Auth Service\nJWT / RBAC]
        C -->|Wallet| E[Wallet Service\nCRUD / Balance]
        C -->|Transfer| F[Transaction Service\nState Machine]
        C -->|Ledger| G[Ledger Service\nDouble-Entry]
        C -->|Fraud| H[Fraud Service\nRisk Scoring]
    end

    subgraph "Data Layer"
        D --> I[(PostgreSQL\nUsers, Roles, Tokens)]
        E --> J[(PostgreSQL\nWallets, Balances)]
        F --> K[(PostgreSQL\nTransactions, Idempotency)]
        G --> L[(PostgreSQL\nLedger Accounts, Entries)]
        H --> M[(PostgreSQL\nFraud Events, Rules)]
        H --> N[(Redis\nVelocity Counters)]
    end

    subgraph "Observability"
        B --> O[Structured Logs\nRequest ID, User ID]
        F --> P[Prometheus Metrics\nLatency, Counters]
        H --> Q[Fraud Alerts\nWebhook/Queue]
    end

    subgraph "Async"
        F -.->|Event| H
        H -.->|HIGH/CRITICAL| R[Review Queue\nCompliance Team]
        G -.->|Reconciliation| S[Background Job\nDaily/Weekly]
    end

    style A fill:#e1f5fe
    style B fill:#fff3e0
    style I fill:#e8f5e9
    style J fill:#e8f5e9
    style K fill:#e8f5e9
    style L fill:#e8f5e9
    style M fill:#e8f5e9
    style N fill:#ffe0b2
    style O fill:#f3e5f5
    style P fill:#f3e5f5
    style Q fill:#ffebee
    style R fill:#ffebee
    style S fill:#fff3e0
```

## Deployment Architecture

```mermaid
C4Deployment
    title FinLedger - Deployment Architecture (Production)

    Deployment_Node(k8s, "Kubernetes Cluster (EKS/GKE/AKS)", "Container Orchestration") {
        Deployment_Node(ingress, "Ingress Controller\n(NGINX/Traefik)", "TLS Termination, Rate Limit") {
            Container(api_pods, "API Pods (x3+)", "FastAPI + Uvicorn", "Horizontal Pod Autoscaler")
        }
        Deployment_Node(worker, "Worker Nodes") {
            Container(celery, "Celery Workers", "Async Tasks", "Fraud, Reconciliation, Webhooks")
            Container(beat, "Celery Beat", "Cron Jobs", "Daily reconciliation, Cleanup")
        }
        Deployment_Node(monitoring_ns, "Monitoring Namespace") {
            Container(prom, "Prometheus", "Metrics Collection")
            Container(grafana, "Grafana", "Dashboards")
            Container(loki, "Loki", "Log Aggregation")
            Container(tempo, "Tempo", "Distributed Tracing")
        }
    }

    Deployment_Node(rds, "AWS RDS / Cloud SQL\nPostgreSQL 16+", "Managed Database") {
        ContainerDb(pg_primary, "Primary", "Read/Write", "Multi-AZ, Automated Backups")
        ContainerDb(pg_replica, "Read Replicas (x2)", "Read Only", "Connection Pooling (PgBouncer)")
    }

    Deployment_Node(elasticache, "ElastiCache / Memorystore\nRedis 7+", "Managed Redis") {
        Container(redis_cluster, "Redis Cluster", "Cache, Sessions, Rate Limit", "Multi-AZ, Auto-failover")
    }

    Deployment_Node(s3, "S3 / GCS", "Object Storage") {
        Container(backups, "Backup Bucket", "DB Backups, Audit Exports")
    }

    Deployment_Node(vault, "HashiCorp Vault / AWS Secrets Manager", "Secrets Management") {
        Container(secrets, "API Keys, DB Creds, JWT Secrets")
    }

    Rel(ingress, api_pods, "HTTPS/Load Balance")
    Rel(api_pods, pg_primary, "AsyncPG/Pool")
    Rel(api_pods, pg_replica, "Read Queries")
    Rel(api_pods, redis_cluster, "Cache/Rate Limit")
    Rel(celery, pg_primary, "AsyncPG/Pool")
    Rel(celery, redis_cluster, "Broker/Backend")
    Rel(api_pods, vault, "Secrets at Startup")
    Rel(prom, api_pods, "Scrape /metrics")
    Rel(loki, api_pods, "Collect Logs")
    Rel(tempo, api_pods, "Traces")
    Rel(pg_primary, backups, "Automated Snapshots")
```

---

## Architecture Decision Records (ADRs)

### ADR-001: Double-Entry Ledger as Core
**Status**: Accepted  
**Context**: Financial systems require immutable, auditable records. Single-entry systems lead to reconciliation nightmares.  
**Decision**: Implement a proper double-entry accounting engine from day one. Every financial movement creates balanced debit/credit entries.  
**Consequences**: More complex initial implementation, but eliminates entire classes of bugs and enables regulatory compliance.

### ADR-002: Optimistic Locking for Ledger Concurrency
**Status**: Accepted  
**Context**: High-throughput financial systems need concurrent transaction processing without deadlocks.  
**Decision**: Use optimistic locking with version columns on ledger_transactions and account_balances. Retry with exponential backoff on conflict.  
**Consequences**: Better throughput under contention vs pessimistic locking; requires idempotent retry logic in clients.

### ADR-003: Three Balance Types (Posted/Pending/Available)
**Status**: Accepted  
**Context**: Real-world wallets need different balance views for different use cases (Modern Treasury pattern).  
**Decision**: Implement three materialized balance types computed from ledger entries with different settlement filters.  
**Consequences**: More storage, but enables correct UX and compliance. Balance drift prevented by transactional updates.

### ADR-004: Rule-Based Fraud Engine (ML-Ready)
**Status**: Accepted  
**Context**: Need immediate fraud protection; ML models require training data and expertise.  
**Decision**: Build configurable rule engine first with clear extension points for ML scoring later.  
**Consequences**: Fast time-to-value, explainable decisions, audit-friendly. ML can be added as a weighted rule.

### ADR-005: Idempotency Keys for All Mutations
**Status**: Accepted  
**Context**: Network failures cause duplicate requests; financial operations must be exactly-once.  
**Decision**: Require `Idempotency-Key` header on all POST/PUT/PATCH. Store key+response in Redis with TTL.  
**Consequences**: Client responsibility, but eliminates duplicate charges. 24hr TTL covers retry windows.

### ADR-006: Async Fraud Evaluation
**Status**: Accepted  
**Context**: Fraud checks add latency; blocking on them hurts UX.  
**Decision**: Evaluate fraud asynchronously via event emission. Only block on CRITICAL risk via callback.  
**Consequences**: Sub-100ms transfer latency; slight risk of post-commit reversal for HIGH risk (handled by review queue).

### ADR-007: Materialized Balance Views
**Status**: Accepted  
**Context**: Computing balances from ledger entries on every read is O(n) and slow at scale.  
**Decision**: Maintain materialized `account_balances` table updated transactionally with ledger entries.  
**Consequences**: Write amplification on transfers, but O(1) balance reads. Reconciliation job verifies consistency.

---

## Non-Functional Requirements

| Requirement | Target | Implementation |
|-------------|--------|----------------|
| **Availability** | 99.95% | Multi-AZ, Health checks, Graceful degradation |
| **Latency (p99)** | < 200ms | Connection pooling, Async, Caching, Indexes |
| **Throughput** | 10,000 TPS | Horizontal scaling, Partitioning, Batch inserts |
| **Durability** | Zero data loss | PostgreSQL WAL, Synchronous replication |
| **Consistency** | Strong (ACID) | Serializable isolation for ledger, MVCC |
| **Auditability** | Complete | Immutable ledger, Structured audit logs |
| **Recoverability** | RPO < 1min, RTO < 5min | Point-in-time recovery, Automated failover |
| **Scalability** | Horizontal | Stateless API, Read replicas, Redis Cluster |