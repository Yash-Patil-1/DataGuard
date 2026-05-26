# 🚀 Deployment Guide

Deploy DataGuard in production environments — from single-server Docker to
Kubernetes clusters and serverless cloud run.

---

## 📋 Table of Contents

- [Docker (Single Server)](#docker-single-server)
- [Docker Compose (Multi-Service)](#docker-compose-multi-service)
- [Kubernetes](#kubernetes)
- [Google Cloud Run](#google-cloud-run)
- [Production Hardening](#production-hardening)
- [Environment Variables Reference](#environment-variables-reference)
- [Health Checks & Monitoring](#health-checks--monitoring)

---

## 🐳 Docker (Single Server)

### Build & Run

```bash
# Build the image
cd DataGuard
docker build -t dataguard:latest .

# Run the dashboard
docker run -d \
  --name dataguard-dashboard \
  -p 8501:8501 \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/reports:/app/reports \
  dataguard:latest \
  streamlit run dashboard.py --server.port=8501 --server.address=0.0.0.0

# Run the pipeline once
docker run --rm \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/reports:/app/reports \
  dataguard:latest \
  python run_pipeline.py --alert
```

### Data Persistence

| Host Path | Container Path | Description |
|-----------|---------------|-------------|
| `./data` | `/app/data` | Generated datasets & DB connectors |
| `./reports` | `/app/reports` | Quality report JSON/TXT output |
| `./config` | `/app/config` | Threshold & alert configurations |
| `./.env` | `/app/.env` | Environment variables (optional) |

---

## 🐳 Docker Compose (Multi-Service)

Start all three services with one command:

```bash
docker compose up -d
```

### Service Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   pipeline   │────▶│  dashboard   │     │  scheduler   │
│  (one-shot)  │     │  (Streamlit) │     │  (continuous)│
│              │     │   :8501      │     │  every 1h    │
└──────┬───────┘     └──────────────┘     └──────▲───────┘
       │                                         │
       ▼                                         │
   ┌────────┐                                    │
   │  data/ │◀───────────────────────────────────┘
   │reports/│
   └────────┘
```

### docker-compose.yml Reference

```yaml
services:
  pipeline:
    build: .
    command: python run_pipeline.py --alert
    volumes:
      - ./data:/app/data
      - ./reports:/app/reports
      - ./config:/app/config
    environment:
      - DATAGUARD_SLACK_WEBHOOK=${DATAGUARD_SLACK_WEBHOOK:-}
      - DATAGUARD_SMTP_HOST=${DATAGUARD_SMTP_HOST:-}
      - DATAGUARD_SMTP_USER=${DATAGUARD_SMTP_USER:-}
    restart: "no"

  dashboard:
    build: .
    command: streamlit run dashboard.py --server.port=8501 --server.address=0.0.0.0
    ports:
      - "8501:8501"
    volumes:
      - ./data:/app/data
      - ./reports:/app/reports
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8501"]
      interval: 30s
      timeout: 10s
      retries: 3

  scheduler:
    build: .
    command: python run_pipeline.py --schedule --interval 3600 --alert
    volumes:
      - ./data:/app/data
      - ./reports:/app/reports
      - ./config:/app/config
    environment:
      - DATAGUARD_SLACK_WEBHOOK=${DATAGUARD_SLACK_WEBHOOK:-}
    restart: unless-stopped
```

> **Tip:** The dashboard's `depends_on` only waits for the *pipeline container to start*, not the pipeline to finish. If data needs to be generated first, run `docker compose run --rm pipeline` before starting the full stack, or add a wait script.

---

## ☸️ Kubernetes

### Minimal Deployment (dashboard only)

```yaml
# dataguard-dashboard.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: dataguard-dashboard
  labels:
    app: dataguard
    component: dashboard
spec:
  replicas: 2
  selector:
    matchLabels:
      app: dataguard
      component: dashboard
  template:
    metadata:
      labels:
        app: dataguard
        component: dashboard
    spec:
      containers:
        - name: dashboard
          image: dataguard:latest
          command: ["streamlit", "run", "dashboard.py",
                    "--server.port=8501",
                    "--server.address=0.0.0.0"]
          ports:
            - containerPort: 8501
          env:
            - name: DATAGUARD_SLACK_WEBHOOK
              valueFrom:
                secretKeyRef:
                  name: dataguard-secrets
                  key: slack-webhook
          resources:
            requests:
              memory: "512Mi"
              cpu: "250m"
            limits:
              memory: "1Gi"
              cpu: "500m"
          livenessProbe:
            httpGet:
              path: /
              port: 8501
            initialDelaySeconds: 30
            periodSeconds: 30
          readinessProbe:
            httpGet:
              path: /
              port: 8501
            initialDelaySeconds: 10
            periodSeconds: 15
          volumeMounts:
            - name: data
              mountPath: /app/data
            - name: reports
              mountPath: /app/reports
      volumes:
        - name: data
          persistentVolumeClaim:
            claimName: dataguard-data
        - name: reports
          persistentVolumeClaim:
            claimName: dataguard-reports
---
apiVersion: v1
kind: Service
metadata:
  name: dataguard-dashboard
spec:
  selector:
    app: dataguard
    component: dashboard
  ports:
    - port: 8501
      targetPort: 8501
  type: ClusterIP
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: dataguard-data
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 10Gi
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: dataguard-reports
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 1Gi
```

### CronJob (Scheduled Pipeline)

```yaml
# dataguard-cronjob.yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: dataguard-pipeline
spec:
  schedule: "0 * * * *"  # Every hour
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - name: pipeline
              image: dataguard:latest
              command: ["python", "run_pipeline.py", "--alert"]
              env:
                - name: DATAGUARD_SLACK_WEBHOOK
                  valueFrom:
                    secretKeyRef:
                      name: dataguard-secrets
                      key: slack-webhook
              volumeMounts:
                - name: data
                  mountPath: /app/data
                - name: reports
                  mountPath: /app/reports
          restartPolicy: OnFailure
          volumes:
            - name: data
              persistentVolumeClaim:
                claimName: dataguard-data
            - name: reports
              persistentVolumeClaim:
                claimName: dataguard-reports
```

### Apply to Cluster

```bash
kubectl create namespace dataguard

# Create secrets
kubectl create secret generic dataguard-secrets \
  --from-literal=slack-webhook='https://hooks.slack.com/services/...' \
  --namespace dataguard

# Deploy
kubectl apply -f dataguard-dashboard.yaml --namespace dataguard
kubectl apply -f dataguard-cronjob.yaml --namespace dataguard

# Check status
kubectl get all --namespace dataguard

# Port-forward to access dashboard locally
kubectl port-forward svc/dataguard-dashboard 8501:8501 --namespace dataguard

# View logs
kubectl logs -l app=dataguard,component=dashboard --namespace dataguard
```

### Ingress (Production)

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: dataguard-ingress
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
    nginx.ingress.kubernetes.io/auth-type: basic
    nginx.ingress.kubernetes.io/auth-secret: dataguard-auth
spec:
  ingressClassName: nginx
  tls:
    - hosts:
        - dataguard.example.com
      secretName: dataguard-tls
  rules:
    - host: dataguard.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: dataguard-dashboard
                port:
                  number: 8501
```

---

## ☁️ Google Cloud Run

For a fully serverless deployment:

```bash
# Build and push
gcloud builds submit --tag gcr.io/your-project/dataguard

# Deploy dashboard
gcloud run deploy dataguard-dashboard \
  --image gcr.io/your-project/dataguard \
  --command "streamlit,run,dashboard.py,--server.port=8080,--server.address=0.0.0.0" \
  --port 8080 \
  --memory 1Gi \
  --cpu 1 \
  --min-instances 0 \
  --max-instances 3 \
  --concurrency 10 \
  --timeout 300 \
  --set-env-vars="DATAGUARD_SLACK_WEBHOOK=..." \
  --allow-unauthenticated \

# Deploy scheduler as a Cloud Run Job
gcloud run jobs create dataguard-scheduler \
  --image gcr.io/your-project/dataguard \
  --command "python,run_pipeline.py,--alert" \
  --memory 2Gi \
  --task-count 1 \
  --max-retries 2 \
  --set-env-vars="DATAGUARD_SLACK_WEBHOOK=..." \

# Schedule with Cloud Scheduler
gcloud scheduler jobs create pubsub dataguard-hourly \
  --schedule="0 * * * *" \
  --topic=dataguard-trigger \
  --message-body="run"

gcloud pubsub subscriptions create dataguard-sub \
  --topic=dataguard-trigger \
  --push-endpoint="https://your-region-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/your-project/jobs/dataguard-scheduler:run"
```

---

## 🔒 Production Hardening

### Security Checklist

- [ ] **Secrets management**: Use Kubernetes Secrets, GCP Secret Manager, or AWS Secrets Manager (never hardcode credentials)
- [ ] **Network security**: Deploy dashboard behind a VPN or use basic auth / OAuth proxy
- [ ] **TLS/HTTPS**: Always terminate TLS at the ingress/load balancer
- [ ] **Resource limits**: Set CPU/memory limits to prevent resource exhaustion
- [ ] **Regular updates**: Keep base image and dependencies patched
- [ ] **Audit logging**: Enable Cloud Audit Logs or Kubernetes audit logging
- [ ] **Backup data**: Schedule periodic backups of `data/` and `reports/`

### Resource Sizing Guide

| Deployment | CPU | Memory | Storage | Notes |
|-----------|-----|--------|---------|-------|
| Dashboard | 0.5–1 core | 512Mi–2Gi | 1Gi (reports) | Scales with concurrent users |
| Pipeline | 1–2 cores | 1–4Gi | 10Gi+ (data) | Higher for DB connectors |
| Scheduler | 0.5 core | 512Mi | Shared | Runs pipeline periodically |
| Database | 1–2 cores | 2–4Gi | 50Gi+ | Only if using PG/Snowflake |

---

## 🌐 Health Checks & Monitoring

### Dashboard Health Endpoint

Streamlit serves a health-checkable page at `/`. Use `healthcheck` configs:

**Docker:**
```dockerfile
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD curl -f http://localhost:8501 || exit 1
```

**Kubernetes (included in the deployment manifest above):**
```yaml
livenessProbe:
  httpGet:
    path: /
    port: 8501
  initialDelaySeconds: 30
  periodSeconds: 30
readinessProbe:
  httpGet:
    path: /
    port: 8501
  initialDelaySeconds: 10
  periodSeconds: 15
```

### Prometheus Metrics (Optional)

To expose pipeline metrics via Prometheus, add the `prometheus-client` library:

```bash
pip install prometheus-client
```

Then create a `metrics.py` entry point:

```python
from prometheus_client import Counter, Gauge, start_http_server

QUALITY_SCORE = Gauge("dataguard_quality_score", "Overall quality score (0–100)")
CHECKS_PASSED = Counter("dataguard_checks_passed_total", "Total passed checks")
CHECKS_FAILED = Counter("dataguard_checks_failed_total", "Total failed checks")
ALERTS_SENT = Counter("dataguard_alerts_sent_total", "Total alerts dispatched")

def expose_metrics(port=9090):
    start_http_server(port)
```

### Alerting Channels

DataGuard supports three alerting channels out of the box:

| Channel | Configuration | Use Case |
|---------|---------------|----------|
| **Slack** | `DATAGUARD_SLACK_WEBHOOK` | Team notifications |
| **Email** | `DATAGUARD_SMTP_*` | On-call escalation |
| **Console** | Built-in | Docker logs / Cloud Logging |

All channels are configured in `config/alerts.yaml` and can be enabled/disabled
independently.

---

## 📋 Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATAGUARD_SLACK_WEBHOOK` | No | — | Slack webhook URL for alerts |
| `DATAGUARD_SMTP_HOST` | No | — | SMTP server hostname |
| `DATAGUARD_SMTP_PORT` | No | `587` | SMTP server port |
| `DATAGUARD_SMTP_USER` | No | — | SMTP username |
| `DATAGUARD_SMTP_PASS` | No | — | SMTP password |
| `DATAGUARD_SMTP_FROM` | No | `dataguard@localhost` | Sender email address |
| `DATAGUARD_ALERT_EMAILS` | No | — | Comma-separated recipient emails |
| `DATAGUARD_PIPELINE_INTERVAL` | No | `3600` | Schedule interval (seconds) |
| `PG_HOST` | No | — | PostgreSQL host (connector) |
| `PG_DB` | No | — | PostgreSQL database name |
| `PG_USER` | No | — | PostgreSQL user |
| `PG_PASSWORD` | No | — | PostgreSQL password |
| `SNOWFLAKE_ACCOUNT` | No | — | Snowflake account ID |
| `SNOWFLAKE_USER` | No | — | Snowflake username |
| `SNOWFLAKE_PASSWORD` | No | — | Snowflake password |
| `SNOWFLAKE_DATABASE` | No | — | Snowflake database name |
| `SNOWFLAKE_WAREHOUSE` | No | — | Snowflake warehouse |

---

> **Next:** See [Development Guide](development.md) for local development setup.
> See [Usage Guide](usage.md) for CLI reference and YAML configuration.
