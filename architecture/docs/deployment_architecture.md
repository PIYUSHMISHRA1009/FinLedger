# FinLedger Deployment Architecture

## Overview

Production-grade deployment architecture designed for high availability, scalability, security, and observability. Supports both containerized (Docker Compose) and orchestrated (Kubernetes) deployments.

## Deployment Topology

```mermaid
C4Deployment
    title FinLedger - Production Deployment Architecture

    Deployment_Node(aws, "AWS Region (us-east-1)", "Cloud Provider") {
        Deployment_Node(vpc, "VPC (10.0.0.0/16)", "Network Isolation") {
            Deployment_Node(public_subnets, "Public Subnets (x3 AZs)", "Internet-facing") {
                Container(alb, "Application Load Balancer", "AWS ALB", "TLS Termination, WAF, Rate Limiting")
                Container(nat, "NAT Gateways (x3)", "AWS NAT", "Outbound Internet Access")
            }
            
            Deployment_Node(private_subnets, "Private Subnets (x3 AZs)", "Application Tier") {
                Deployment_Node(eks, "EKS Cluster v1.28+", "Kubernetes") {
                    Deployment_Node(system_ns, "system namespace") {
                        Container(coredns, "CoreDNS", "Service Discovery")
                        Container(metrics, "Metrics Server", "HPA Metrics")
                        Container(ebs_csi, "EBS CSI Driver", "Persistent Volumes")
                    }
                    
                    Deployment_Node(app_ns, "finledger namespace") {
                        Container(api_deployment, "API Deployment (x3+)", "FastAPI + Uvicorn", "HPA: CPU>70%, Memory>80%, Custom: rps>1000")
                        Container(celery_workers, "Celery Workers (x5+)", "Python Celery", "Fraud, Reconciliation, Webhooks\nConcurrency: 4, Prefetch: 10")
                        Container(celery_beat, "Celery Beat (x1)", "Python Celery Beat", "Cron: Reconciliation, Cleanup")
                    }
                    
                    Deployment_Node(monitoring_ns, "monitoring namespace") {
                        Container(prometheus, "Prometheus (HA)", "Prometheus Operator", "2 replicas, 30d retention")
                        Container(grafana, "Grafana (HA)", "Grafana Operator", "2 replicas, Dashboards as Code")
                        Container(loki, "Loki", "Grafana Loki", "Log aggregation, 14d retention")
                        Container(tempo, "Tempo", "Grafana Tempo", "Distributed tracing")
                        Container(alertmanager, "Alertmanager", "Prometheus Alertmanager", "HA, PagerDuty/Slack/Email")
                    }
                    
                    Deployment_Node(data_ns, "data namespace") {
                        Container(pgbouncer, "PgBouncer (x3)", "Connection Pooler", "Transaction mode, 100 max conn")
                        Container(redis, "Redis Cluster (x6)", "ElastiCache Redis 7", "3 shards, 2 replicas each")
                    }
                }
            }
            
            Deployment_Node(data_subnets, "Data Subnets (x3 AZs)", "Managed Services") {
                Container(rds, "RDS PostgreSQL 16", "Multi-AZ Cluster", "Primary + 2 Read Replicas\nInstance: db.r6g.2xlarge\nStorage: 500GB gp3\nBackup: 30d, Point-in-time")
                Container(elasticache, "ElastiCache Redis 7", "Cluster Mode", "3 Shards, Multi-AZ\nInstance: cache.r6g.xlarge")
                Container(s3, "S3 Buckets", "Object Storage", "Backups, Audit Exports, Static Assets\nVersioning, Encryption, Lifecycle")
            }
        }
        
        Deployment_Node(security, "Security Services") {
            Container(secrets, "AWS Secrets Manager", "Secrets", "DB Credentials, JWT Keys, API Keys\nAutomatic Rotation")
            Container(kms, "AWS KMS", "Key Management", "Envelope Encryption, Key Rotation")
            Container(waf, "AWS WAF", "Web App Firewall", "Rate Rules, IP Reputation, SQLi/XSS")
            Container(shield, "AWS Shield Advanced", "DDoS Protection", "Always-on, Layer 3/4/7")
        }
    }
    
    Deployment_Node(external, "External Systems") {
        Container(payment_rails, "Payment Rails", "ACH, Wire, RTP, Card Networks")
        Container(kyc, "KYC/AML Providers", "Identity Verification")
        Container(email, "Email Service", "SendGrid/SES")
        Container(slack, "Slack/PagerDuty", "Alerting")
    }

    Rel(alb, api_deployment, "HTTPS/443\nALB → Target Group")
    Rel(api_deployment, pgbouncer, "PostgreSQL/5432\nPool: 20-100 conn")
    Rel(api_deployment, redis, "Redis/6379\nCluster Client")
    Rel(celery_workers, pgbouncer, "PostgreSQL/5432")
    Rel(celery_workers, redis, "Redis/6379\nBroker + Backend")
    Rel(pgbouncer, rds, "PostgreSQL/5432")
    Rel(api_deployment, secrets, "Secrets at Startup")
    Rel(prometheus, api_deployment, "Scrape /metrics")
    Rel(loki, api_deployment, "Collect Logs")
    Rel(tempo, api_deployment, "Traces (OTLP)")
    Rel(api_deployment, payment_rails, "mTLS/VPN")
    Rel(api_deployment, kyc, "HTTPS/mTLS")
    Rel(alb, waf, "Traffic Inspection")
```

## Infrastructure as Code (Terraform)

### Module Structure
```
infrastructure/
├── modules/
│   ├── vpc/                    # VPC, Subnets, NAT, IGW
│   ├── eks/                    # EKS Cluster, Node Groups, Add-ons
│   ├── rds/                    # PostgreSQL Cluster, Replicas, Parameter Groups
│   ├── elasticache/            # Redis Cluster, Subnet Groups
│   ├── alb/                    # ALB, Target Groups, WAF Integration
│   ├── iam/                    # Roles, Policies, OIDC Provider
│   ├── monitoring/             # Prometheus, Grafana, Loki, Tempo
│   └── secrets/                # Secrets Manager, KMS Keys
├── environments/
│   ├── dev/
│   ├── staging/
│   └── prod/
└── main.tf
```

### Key Terraform Resources

```hcl
# EKS Cluster with Managed Node Groups
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 19.0"
  
  cluster_name    = "finledger-${var.environment}"
  cluster_version = "1.28"
  
  vpc_id                         = module.vpc.vpc_id
  subnet_ids                     = module.vpc.private_subnets
  cluster_endpoint_public_access = true
  
  eks_managed_node_groups = {
    general = {
      name           = "general"
      instance_types = ["m6i.xlarge", "m6i.2xlarge"]
      capacity_type  = "ON_DEMAND"
      
      scaling_config = {
        desired_size = 3
        max_size     = 20
        min_size     = 3
      }
      
      labels = {
        workload-type = "general"
      }
      
      taints = [{
        key    = "workload"
        value  = "general"
        effect = "PREFER_NO_SCHEDULE"
      }]
    }
    
    workers = {
      name           = "workers"
      instance_types = ["m6i.2xlarge", "m6i.4xlarge"]
      capacity_type  = "SPOT"
      
      scaling_config = {
        desired_size = 5
        max_size     = 50
        min_size     = 2
      }
      
      labels = {
        workload-type = "batch"
      }
    }
  }
  
  # IRSA for AWS services
  enable_irsa = true
}
```

```hcl
# RDS PostgreSQL with Read Replicas
module "rds" {
  source  = "terraform-aws-modules/rds/aws"
  version = "~> 6.0"
  
  identifier = "finledger-${var.environment}"
  
  engine               = "postgres"
  engine_version       = "16.2"
  instance_class       = "db.r6g.2xlarge"
  allocated_storage    = 500
  max_allocated_storage = 1000
  storage_type         = "gp3"
  storage_encrypted    = true
  kms_key_id           = module.kms.key_arn
  
  db_name  = "finledger"
  username = "admin"
  password = random_password.db_password.result
  port     = 5432
  
  multi_az               = true
  backup_retention_period = 30
  backup_window          = "03:00-04:00"
  maintenance_window     = "sun:04:00-sun:05:00"
  
  # Read replicas
  replicas = [
    {
      identifier = "finledger-${var.environment}-replica-1"
      instance_class = "db.r6g.xlarge"
    },
    {
      identifier = "finledger-${var.environment}-replica-2"
      instance_class = "db.r6g.xlarge"
    }
  ]
  
  # Parameter group for performance
  parameter_group_name = "finledger-pg16"
  
  vpc_id            = module.vpc.vpc_id
  subnet_ids        = module.vpc.data_subnets
  security_group_ids = [module.security_groups.rds.id]
}
```

```hcl
# PgBouncer Deployment (Kubernetes)
resource "kubernetes_deployment" "pgbouncer" {
  metadata {
    name      = "pgbouncer"
    namespace = "data"
    labels = { app = "pgbouncer" }
  }
  
  spec {
    replicas = 3
    selector { match_labels = { app = "pgbouncer" } }
    
    template {
      metadata { labels = { app = "pgbouncer" } }
      
      spec {
        container {
          name  = "pgbouncer"
          image = "edoburu/pgbouncer:1.21"
          
          env = [
            { name = "DATABASE_URL", value = "postgresql://${var.db_user}:${var.db_pass}@${module.rds.writer_endpoint}/finledger" },
            { name = "POOL_MODE", value = "transaction" },
            { name = "MAX_CLIENT_CONN", value = "1000" },
            { name = "DEFAULT_POOL_SIZE", value = "20" },
            { name = "MIN_POOL_SIZE", value = "5" },
            { name = "RESERVE_POOL_SIZE", value = "5" },
            { name = "RESERVE_POOL_TIMEOUT", value = "5" }
          ]
          
          resources {
            limits = { cpu = "500m", memory = "512Mi" }
            requests = { cpu = "100m", memory = "128Mi" }
          }
          
          liveness_probe {
            exec { command = ["pg_isready", "-p", "6432"] }
            initial_delay_seconds = 10
            period_seconds = 10
          }
        }
      }
    }
  }
}
```

## Kubernetes Manifests

### API Deployment
```yaml
# k8s/base/api-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: finledger-api
  namespace: finledger
  labels:
    app: finledger-api
    version: v1
spec:
  replicas: 3
  selector:
    matchLabels:
      app: finledger-api
  template:
    metadata:
      labels:
        app: finledger-api
        version: v1
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "8000"
        prometheus.io/path: "/metrics"
    spec:
      serviceAccountName: finledger-api
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        fsGroup: 1000
      containers:
      - name: api
        image: ghcr.io/yourorg/finledger-api:latest
        imagePullPolicy: Always
        ports:
        - containerPort: 8000
          name: http
        env:
        - name: ENVIRONMENT
          value: "production"
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: finledger-secrets
              key: database-url
        - name: REDIS_URL
          valueFrom:
            secretKeyRef:
              name: finledger-secrets
              key: redis-url
        - name: JWT_PRIVATE_KEY
          valueFrom:
            secretKeyRef:
              name: finledger-secrets
              key: jwt-private-key
        - name: JWT_PUBLIC_KEY
          valueFrom:
            secretKeyRef:
              name: finledger-secrets
              key: jwt-public-key
        resources:
          requests:
            cpu: "500m"
            memory: "512Mi"
          limits:
            cpu: "2000m"
            memory: "2Gi"
        livenessProbe:
          httpGet:
            path: /health/live
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 10
          timeoutSeconds: 5
          failureThreshold: 3
        readinessProbe:
          httpGet:
            path: /health/ready
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 5
          timeoutSeconds: 3
          failureThreshold: 3
        startupProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 5
          timeoutSeconds: 3
          failureThreshold: 30
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
          - weight: 100
            podAffinityTerm:
              labelSelector:
                matchExpressions:
                - key: app
                  operator: In
                  values: [finledger-api]
              topologyKey: kubernetes.io/hostname
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: finledger-api-hpa
  namespace: finledger
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: finledger-api
  minReplicas: 3
  maxReplicas: 50
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
  - type: Pods
    pods:
      metric:
        name: http_requests_per_second
      target:
        type: AverageValue
        averageValue: "1000"
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
      - type: Percent
        value: 10
        periodSeconds: 60
    scaleUp:
      stabilizationWindowSeconds: 0
      policies:
      - type: Percent
        value: 100
        periodSeconds: 15
      - type: Pods
        value: 4
        periodSeconds: 15
      selectPolicy: Max
```

### Service & Ingress
```yaml
# k8s/base/api-service.yaml
apiVersion: v1
kind: Service
metadata:
  name: finledger-api
  namespace: finledger
  annotations:
    service.beta.kubernetes.io/aws-load-balancer-type: "nlb"
    service.beta.kubernetes.io/aws-load-balancer-cross-zone-load-balancing-enabled: "true"
spec:
  type: LoadBalancer
  selector:
    app: finledger-api
  ports:
  - port: 443
    targetPort: 8000
    protocol: TCP
    name: https
---
# k8s/base/api-ingress.yaml (for ALB)
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: finledger-api
  namespace: finledger
  annotations:
    kubernetes.io/ingress.class: alb
    alb.ingress.kubernetes.io/scheme: internet-facing
    alb.ingress.kubernetes.io/target-type: ip
    alb.ingress.kubernetes.io/certificate-arn: arn:aws:acm:us-east-1:123456789:certificate/xxx
    alb.ingress.kubernetes.io/listen-ports: '[{"HTTP": 80}, {"HTTPS": 443}]'
    alb.ingress.kubernetes.io/ssl-redirect: 'true'
    alb.ingress.kubernetes.io/wafv2-acl-arn: arn:aws:wafv2:us-east-1:123456789:global/webacl/finledger-waf/xxx
spec:
  rules:
  - host: api.finledger.io
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: finledger-api
            port:
              number: 443
```

### Celery Workers
```yaml
# k8s/base/celery-workers.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: finledger-celery-workers
  namespace: finledger
spec:
  replicas: 5
  selector:
    matchLabels:
      app: finledger-celery-workers
  template:
    metadata:
      labels:
        app: finledger-celery-workers
    spec:
      serviceAccountName: finledger-worker
      containers:
      - name: worker
        image: ghcr.io/yourorg/finledger-api:latest
        command: ["celery", "-A", "src.core.celery_app", "worker", "--loglevel=info", "--concurrency=4", "--prefetch-multiplier=10", "--max-tasks-per-child=1000"]
        env:
        - name: ENVIRONMENT
          value: "production"
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: finledger-secrets
              key: database-url
        - name: REDIS_URL
          valueFrom:
            secretKeyRef:
              name: finledger-secrets
              key: redis-url
        resources:
          requests:
            cpu: "500m"
            memory: "1Gi"
          limits:
            cpu: "2000m"
            memory: "4Gi"
---
apiVersion: batch/v1
kind: CronJob
metadata:
  name: finledger-celery-beat
  namespace: finledger
spec:
  schedule: "0 2 * * *"  # Daily at 2 AM UTC
  jobTemplate:
    spec:
      template:
        spec:
          serviceAccountName: finledger-worker
          containers:
          - name: beat
            image: ghcr.io/yourorg/finledger-api:latest
            command: ["celery", "-A", "src.core.celery_app", "beat", "--loglevel=info", "--scheduler=django_celery_beat.schedulers:DatabaseScheduler"]
            env:
            - name: ENVIRONMENT
              value: "production"
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: finledger-secrets
                  key: database-url
            - name: REDIS_URL
              valueFrom:
                secretKeyRef:
                  name: finledger-secrets
                  key: redis-url
          restartPolicy: OnFailure
```

## Docker Images

### Multi-stage Dockerfile
```dockerfile
# docker/Dockerfile
# Build stage
FROM python:3.11-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt requirements-prod.txt ./
RUN pip install --no-cache-dir --user -r requirements-prod.txt

# Runtime stage
FROM python:3.11-slim as runtime

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy Python packages from builder
COPY --from=builder /root/.local /home/appuser/.local

# Copy application code
COPY --chown=appuser:appuser src/ ./src/
COPY --chown=appuser:appuser scripts/ ./scripts/
COPY --chown=appuser:appuser alembic/ ./alembic/
COPY --chown=appuser:appuser alembic.ini ./

# Switch to non-root user
USER appuser

# Add local packages to PATH
ENV PATH=/home/appuser/.local/bin:$PATH

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health/live || exit 1

# Run application
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

### Docker Compose (Development)
```yaml
# docker/docker-compose.yml
version: '3.8'

services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: finledger
      POSTGRES_USER: finledger
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-dev_password}
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U finledger"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5

  api:
    build:
      context: ..
      dockerfile: docker/Dockerfile
      target: runtime
    ports:
      - "8000:8000"
    environment:
      - ENVIRONMENT=development
      - DATABASE_URL=postgresql+asyncpg://finledger:dev_password@postgres:5432/finledger
      - REDIS_URL=redis://redis:6379/0
      - JWT_SECRET_KEY=${JWT_SECRET_KEY:-dev_secret_change_in_prod}
      - JWT_ALGORITHM=RS256
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    volumes:
      - ../src:/app/src:ro
    command: uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload

  celery-worker:
    build:
      context: ..
      dockerfile: docker/Dockerfile
      target: runtime
    environment:
      - ENVIRONMENT=development
      - DATABASE_URL=postgresql+asyncpg://finledger:dev_password@postgres:5432/finledger
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    command: celery -A src.core.celery_app worker --loglevel=info --concurrency=2

  celery-beat:
    build:
      context: ..
      dockerfile: docker/Dockerfile
      target: runtime
    environment:
      - ENVIRONMENT=development
      - DATABASE_URL=postgresql+asyncpg://finledger:dev_password@postgres:5432/finledger
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    command: celery -A src.core.celery_app beat --loglevel=info

  prometheus:
    image: prom/prometheus:v2.48
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus_data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'

  grafana:
    image: grafana/grafana:10.2
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_USER=admin
      - GF_SECURITY_ADMIN_PASSWORD=admin
    volumes:
      - grafana_data:/var/lib/grafana
      - ./grafana/dashboards:/etc/grafana/provisioning/dashboards:ro
      - ./grafana/datasources:/etc/grafana/provisioning/datasources:ro

volumes:
  postgres_data:
  redis_data:
  prometheus_data:
  grafana_data:
```

## CI/CD Pipeline (GitHub Actions)

```yaml
# .github/workflows/ci-cd.yaml
name: CI/CD

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: ${{ github.repository }}

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_DB: finledger_test
          POSTGRES_USER: test
          POSTGRES_PASSWORD: test
        ports: [5432:5432]
        options: >-
          --health-cmd "pg_isready -U test"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
      redis:
        image: redis:7-alpine
        ports: [6379:6379]
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

    steps:
    - uses: actions/checkout@v4
    
    - name: Set up Python
      uses: actions/setup-python@v5
      with:
        python-version: '3.11'
        cache: 'pip'
    
    - name: Install dependencies
      run: |
        pip install -r requirements.txt -r requirements-dev.txt
        pip install -e .
    
    - name: Run migrations
      run: alembic upgrade head
      env:
        DATABASE_URL: postgresql+asyncpg://test:test@localhost:5432/finledger_test
    
    - name: Run tests
      run: |
        pytest --cov=src --cov-report=xml --cov-fail-under=80
      env:
        DATABASE_URL: postgresql+asyncpg://test:test@localhost:5432/finledger_test
        REDIS_URL: redis://localhost:6379/0
        JWT_SECRET_KEY: test_secret
    
    - name: Upload coverage
      uses: codecov/codecov-action@v4

  build:
    needs: test
    runs-on: ubuntu-latest
    if: github.event_name == 'push'
    outputs:
      image: ${{ steps.image.outputs.image }}
    steps:
    - uses: actions/checkout@v4
    
    - name: Set up Docker Buildx
      uses: docker/setup-buildx-action@v3
    
    - name: Log in to Container Registry
      uses: docker/login-action@v3
      with:
        registry: ${{ env.REGISTRY }}
        username: ${{ github.actor }}
        password: ${{ secrets.GITHUB_TOKEN }}
    
    - name: Extract metadata
      id: meta
      uses: docker/metadata-action@v5
      with:
        images: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}
        tags: |
          type=ref,event=branch
          type=sha,prefix=
          type=raw,value=latest,enable={{is_default_branch}}
    
    - name: Build and push
      id: image
      uses: docker/build-push-action@v5
      with:
        context: .
        file: docker/Dockerfile
        push: true
        tags: ${{ steps.meta.outputs.tags }}
        labels: ${{ steps.meta.outputs.labels }}
        cache-from: type=gha
        cache-to: type=gha,mode=max

  deploy-staging:
    needs: build
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/develop'
    environment: staging
    steps:
    - name: Deploy to Staging
      run: |
        kubectl set image deployment/finledger-api \
          api=${{ needs.build.outputs.image }} \
          -n finledger-staging
        kubectl rollout status deployment/finledger-api -n finledger-staging --timeout=300s

  deploy-production:
    needs: build
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    environment: production
    steps:
    - name: Deploy to Production
      run: |
        # Blue-green deployment via ArgoCD or Flux
        kubectl set image deployment/finledger-api \
          api=${{ needs.build.outputs.image }} \
          -n finledger
        kubectl rollout status deployment/finledger-api -n finledger --timeout=600s
      
    - name: Run smoke tests
      run: |
        curl -f https://api.finledger.io/health/ready
        curl -f https://api.finledger.io/health/live
```

## Monitoring & Alerting

### Prometheus Rules
```yaml
# k8s/monitoring/prometheus-rules.yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: finledger-alerts
  namespace: monitoring
spec:
  groups:
  - name: finledger-api
    rules:
    - alert: APIHighErrorRate
      expr: |
        sum(rate(http_requests_total{job="finledger-api",status=~"5.."}[5m]))
        /
        sum(rate(http_requests_total{job="finledger-api"}[5m])) > 0.05
      for: 2m
      labels:
        severity: critical
      annotations:
        summary: "High error rate on FinLedger API"
        description: "Error rate > 5% for 2 minutes"

    - alert: APIHighLatency
      expr: |
        histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket{job="finledger-api"}[5m])) by (le)) > 1
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "High API latency"
        description: "p99 latency > 1s for 5 minutes"

    - alert: TransactionFailureRate
      expr: |
        sum(rate(transaction_failed_total[5m]))
        /
        sum(rate(transaction_created_total[5m])) > 0.02
      for: 3m
      labels:
        severity: critical
      annotations:
        summary: "High transaction failure rate"
        description: "Failure rate > 2% for 3 minutes"

    - alert: FraudReviewQueueBacklog
      expr: |
        fraud_review_queue_size{priority="1"} > 50
      for: 10m
      labels:
        severity: warning
      annotations:
        summary: "Fraud review queue backlog"
        description: "CRITICAL priority queue has > 50 items"

    - alert: DatabaseConnectionsHigh
      expr: |
        pg_stat_database_numbackends / pg_settings_max_connections > 0.8
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "Database connection pool near exhaustion"

    - alert: RedisMemoryHigh
      expr: |
        redis_memory_used_bytes / redis_memory_max_bytes > 0.85
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "Redis memory usage high"

  - name: finledger-infrastructure
    rules:
    - alert: PodNotReady
      expr: |
        kube_pod_status_ready{namespace="finledger",condition="true"} == 0
      for: 5m
      labels:
        severity: critical
      annotations:
        summary: "Pod not ready"
        description: "{{ $labels.pod }} in {{ $labels.namespace }} not ready for 5m"

    - alert: HPAReplicasAtMax
      expr: |
        kube_hpa_status_current_replicas == kube_hpa_spec_max_replicas
      for: 10m
      labels:
        severity: warning
      annotations:
        summary: "HPA at max replicas"
        description: "{{ $labels.hpa }} at max replicas for 10m"
```

### Grafana Dashboards
Key dashboards (provisioned as code):
1. **API Overview** - Request rate, latency, errors, saturation (RED)
2. **Transaction Flow** - Volume, success rate, latency by type
3. **Fraud Engine** - Risk score distribution, review queue, rule triggers
4. **Ledger Health** - Trial balance, reconciliation status, entry rate
5. **Database** - Connections, query latency, replication lag
6. **Infrastructure** - CPU, memory, network, disk per pod/node

## Security Hardening

### Network Policies
```yaml
# k8s/security/network-policies.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: api-ingress
  namespace: finledger
spec:
  podSelector:
    matchLabels:
      app: finledger-api
  policyTypes:
  - Ingress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          name: ingress-nginx
    ports:
    - protocol: TCP
      port: 8000
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: api-egress
  namespace: finledger
spec:
  podSelector:
    matchLabels:
      app: finledger-api
  policyTypes:
  - Egress
  egress:
  - to:
    - podSelector:
        matchLabels:
          app: pgbouncer
    ports:
    - protocol: TCP
      port: 6432
  - to:
    - podSelector:
        matchLabels:
          app: redis
    ports:
    - protocol: TCP
      port: 6379
  - to:
    - namespaceSelector: {}
    ports:
    - protocol: TCP
      port: 53  # DNS
    - protocol: UDP
      port: 53
```

### Pod Security Standards
```yaml
# All pods run with:
securityContext:
  runAsNonRoot: true
  runAsUser: 1000
  runAsGroup: 1000
  fsGroup: 1000
  readOnlyRootFilesystem: true
  allowPrivilegeEscalation: false
  capabilities:
    drop: ["ALL"]
  seccompProfile:
    type: RuntimeDefault
```

## Disaster Recovery

### Backup Strategy
| Component | Frequency | Retention | Recovery |
|-----------|-----------|-----------|----------|
| RDS PostgreSQL | Continuous (PITR) | 30 days | Point-in-time to any second |
| RDS Snapshots | Daily | 90 days | Full restore |
| Redis | AOF + RDB | 7 days | Replica promotion |
| S3 Audit Exports | Daily | 7 years | Immutable, versioned |
| Kubernetes Etcd | Hourly | 30 days | Cluster restore |

### RTO/RPO Targets
| Scenario | RTO | RPO |
|----------|-----|-----|
| Single AZ failure | < 2 min | 0 (Multi-AZ) |
| Region failure | < 15 min | < 1 min (Cross-region replica) |
| Data corruption | < 1 hour | < 1 min (PITR) |
| Accidental deletion | < 30 min | 0 (Snapshots) |

### Runbooks
- `RUNBOOK-001`: Database failover
- `RUNBOOK-002`: Redis cluster recovery
- `RUNBOOK-003`: Kubernetes cluster rebuild
- `RUNBOOK-004`: Fraud queue processing
- `RUNBOOK-005`: Reconciliation discrepancy investigation

## Cost Optimization

| Component | Strategy | Estimated Monthly (US-East-1) |
|-----------|----------|------------------------------|
| EKS Control Plane | Standard | $73 |
| EC2 (3x m6i.xlarge + 5x m6i.2xlarge Spot) | Spot + Savings Plans | $1,200 |
| RDS (db.r6g.2xlarge Multi-AZ + 2 replicas) | Reserved Instances | $2,800 |
| ElastiCache (3 shard r6g.xlarge) | Reserved | $1,500 |
| ALB + Data Transfer | Pay-per-use | $200 |
| Monitoring (Prometheus/Grafana/Loki/Tempo) | Self-hosted on EKS | $300 |
| S3 + CloudWatch | Pay-per-use | $100 |
| **Total** | | **~$6,173/month** |

*With 1-year Reserved Instances and Savings Plans: ~$4,200/month*