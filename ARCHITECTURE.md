# CalvinCode Runtime Architecture

## Overview

CalvinCode Runtime is a platform that allows customers to deploy and run their custom containerized applications with auto-scaling, scheduled triggers, and metrics tracking.

## Core Components

### 1. Infrastructure Layer

#### Kubernetes Cluster (DigitalOcean)
- Managed Kubernetes cluster
- Hosts all platform components
- Network: Wildcard DNS `*.calvinruntime.net` → Kourier ingress

#### Knative Serving
- **Purpose**: Serverless runtime for auto-scaling workloads
- **Why it's required**: KServe is built on top of Knative
- **Features**:
  - Scale-to-zero capability
  - Automatic scaling (0-10 pods)
  - Traffic management
  - Revision management
  - Built-in networking via Kourier

#### KServe
- **Purpose**: Platform for deploying customer applications
- **Built on**: Knative Serving (depends on it)
- **What it does**:
  - Accepts customer Docker images
  - Creates InferenceService resources
  - Automatically creates Knative Services
  - Manages auto-scaling (min-scale: 0, max-scale: 10)
  - Provides clean URLs via DomainMapping

**Important**: KServe is NOT just for ML inference. We use it as a general-purpose app deployment platform with auto-scaling.

---

### 2. Platform Services (Infrastructure)

These are the services WE maintain to run the platform:

#### kserve-api (Python/FastAPI)
- **What**: Management API for deploying customer apps
- **Deployment**: Knative Service (min-scale: 1, max-scale: 5)
- **URL**: `https://kserve-api.calvinruntime.net`
- **Code**: `/root/kserve-api/`
- **Responsibilities**:
  - Accepts deployment requests (POST /deploy)
  - Creates/updates/deletes InferenceService resources
  - Creates DomainMapping for clean URLs
  - Fixes KServe scale-to-zero issues
  - Lists and manages customer apps
  - Fetches logs from customer apps

**API Endpoints**:
```bash
# Deploy/update an app
POST /deploy
{
  "name": "my-app",
  "image": "registry.digitalocean.com/calvin-apps/my-app:latest",
  "envs": {"KEY": "value"}
}

# List all apps
GET /models

# Get app details
GET /models/{namespace}/{name}

# Delete app
DELETE /models/{namespace}/{name}

# Get app logs
GET /logs/{name}?tail_lines=100
```

#### scheduler-api (Node.js/Express)
- **What**: Cron-based job scheduler to trigger customer apps
- **Deployment**: Regular Deployment (replicas: 2) + Regular Service + DomainMapping
- **URL**: `https://scheduler-api.calvinruntime.net`
- **Code**: `/root/scheduler-api/`
- **Why not Knative**: Needs to always be running (background workers), doesn't benefit from scale-to-zero
- **Responsibilities**:
  - Accepts workspace trigger configurations
  - Schedules cron jobs using BullMQ
  - Executes HTTP requests to customer apps on schedule
  - Collects and stores execution metrics to S3
  - Provides metrics dashboard

**API Endpoints**:
```bash
# Create/update workspace triggers
POST /api/workspaces/{workspace_id}/triggers
{
  "triggers": [
    {
      "cron": "*/5 * * * *",
      "url": "https://my-app.calvinruntime.net/endpoint",
      "method": "POST",
      "headers": {"Content-Type": "application/json"},
      "body": {"data": "value"}
    }
  ]
}

# Get workspace triggers
GET /api/workspaces/{workspace_id}/triggers

# Delete workspace triggers
DELETE /api/workspaces/{workspace_id}/triggers

# View metrics dashboard
GET /metrics?workspace_id={workspace_id}

# Get metrics data (API)
GET /metrics/api/{workspace_id}

# Bull Board queue dashboard
GET /admin/queues
```

#### scheduler-worker
- **What**: Background worker that executes scheduled jobs
- **Deployment**: Regular Deployment (replicas: 1)
- **Responsibilities**:
  - Processes jobs from BullMQ queue
  - Makes HTTP requests to customer apps
  - Logs execution metrics (success/failure, duration, retries)
  - Retries failed jobs (3 attempts with exponential backoff)

---

### 3. Customer Apps (Deployed by Customers)

#### How Customer Apps Are Deployed

1. **Customer sends request to kserve-api**:
   ```bash
   POST https://kserve-api.calvinruntime.net/deploy
   {
     "name": "my-app",
     "image": "registry.digitalocean.com/my-org/my-app:v1.0.0",
     "envs": {"DATABASE_URL": "..."}
   }
   ```

2. **kserve-api creates InferenceService**:
   ```yaml
   apiVersion: serving.kserve.io/v1beta1
   kind: InferenceService
   metadata:
     name: my-app
     annotations:
       autoscaling.knative.dev/min-scale: "0"
       autoscaling.knative.dev/max-scale: "10"
   spec:
     predictor:
       containers:
         - name: kserve-container
           image: registry.digitalocean.com/my-org/my-app:v1.0.0
           port: 8080
   ```

3. **KServe automatically creates Knative Service**:
   - KServe creates a Knative Service named `my-app-predictor`
   - Knative handles auto-scaling, networking

4. **DomainMapping for clean URL**:
   ```yaml
   apiVersion: serving.knative.dev/v1beta1
   kind: DomainMapping
   metadata:
     name: my-app.calvinruntime.net
   spec:
     ref:
       name: my-app-predictor
       kind: Service
   ```

5. **Customer app is accessible**:
   - URL: `https://my-app.calvinruntime.net`
   - Auto-scales from 0 to 10 pods based on traffic
   - Scales to zero after inactivity

---

## Architecture Diagrams

### Customer App Deployment Flow

```
Customer
   ↓
POST https://kserve-api.calvinruntime.net/deploy
   ↓
kserve-api (Python)
   ↓
Creates InferenceService (KServe CRD)
   ↓
KServe Controller
   ↓
Creates Knative Service (automatic)
   ↓
Knative Controller
   ↓
Creates Deployment, Service, etc.
   ↓
Customer App Pods (auto-scaling 0-10)
   ↓
Exposed via DomainMapping
   ↓
https://my-app.calvinruntime.net
```

### Scheduler Trigger Flow

```
Customer
   ↓
POST https://scheduler-api.calvinruntime.net/api/workspaces/{id}/triggers
   ↓
scheduler-api
   ↓
Creates BullMQ jobs with cron patterns
   ↓
Redis Queue
   ↓
scheduler-worker picks up jobs
   ↓
Executes HTTP request to customer app
   ↓
https://my-app.calvinruntime.net/endpoint
   ↓
Logs metrics to S3 (success/failure, duration, retries)
```

### Metrics Collection Flow

```
scheduler-worker executes job
   ↓
Collects metrics (timestamp, status, duration, http_status, retries)
   ↓
Buffers in memory (100 jobs or 60 seconds)
   ↓
Writes to S3 in JSON format
   ↓
s3://calvin-runtime-scheduler/metrics/year=2025/month=11/day=16/hour=15/metrics-{timestamp}.json
   ↓
Customer views at https://scheduler-api.calvinruntime.net/metrics?workspace_id={id}
   ↓
Dashboard queries S3, shows stats and charts
```

---

## Technology Stack

### Infrastructure
- **Kubernetes**: Container orchestration (DigitalOcean Managed)
- **Knative Serving**: Serverless platform with auto-scaling
- **KServe**: Application deployment platform (built on Knative)
- **Kourier**: Ingress controller (part of Knative)
- **DomainMapping**: Maps custom domains to services

### Platform Services
- **kserve-api**: Python 3.11, FastAPI, Kubernetes Python Client
- **scheduler-api**: Node.js 20, Express, BullMQ
- **scheduler-worker**: Node.js 20, BullMQ worker, Axios

### Data Storage
- **Redis**: BullMQ queue storage (DigitalOcean Managed Redis with TLS)
- **S3/DigitalOcean Spaces**: Metrics storage (JSON format, partitioned by date)

### Container Registry
- **DigitalOcean Container Registry**: Stores all Docker images
  - Platform images: `registry.digitalocean.com/calvin-apps/`
  - Customer images: Customers provide their own registry URLs

---

## Networking & DNS

### Wildcard DNS
- `*.calvinruntime.net` → Points to Kourier LoadBalancer
- Cloudflare provides wildcard SSL certificate
- All services automatically get HTTPS

### Service Exposure Methods

1. **Knative Services** (customer apps, kserve-api):
   - Automatically exposed by Knative
   - Get `{name}.calvinruntime.net` via DomainMapping
   - Example: `https://my-app.calvinruntime.net`

2. **Regular Services** (scheduler-api):
   - Deployment + ClusterIP Service
   - DomainMapping points to regular Service
   - Example: `https://scheduler-api.calvinruntime.net`

---

## Resource Limits & Scaling

### Customer Apps (KServe)
- **Auto-scaling**: 0 to 10 pods
- **Scale-to-zero**: Yes (saves resources when idle)
- **Resources per pod**:
  - CPU: 100m request, 1 CPU limit
  - Memory: 128Mi request, 512Mi limit
- **Port**: 8080 (required)

### Platform Services

**kserve-api**:
- **Scaling**: 1 to 5 pods (Knative)
- **Resources per pod**:
  - CPU: 100m request, 500m limit
  - Memory: 128Mi request, 512Mi limit
- **Always running**: min-scale: 1

**scheduler-api**:
- **Scaling**: 2 replicas (fixed)
- **Resources per pod**:
  - CPU: 200m request, 500m limit
  - Memory: 256Mi request, 512Mi limit
- **Always running**: Regular Deployment

**scheduler-worker**:
- **Scaling**: 1 replica (fixed)
- **Resources**: Same as scheduler-api
- **Always running**: Regular Deployment

---

## Data Persistence

### Metrics Storage (S3)
- **Format**: JSON (one file per flush)
- **Partitioning**: `metrics/year={year}/month={month}/day={day}/hour={hour}/`
- **Retention**: Configurable (currently unlimited)
- **Buffer**: 100 jobs or 60 seconds, whichever comes first
- **Schema**:
  ```json
  {
    "workspace_id": "my-workspace",
    "job_id": "repeat:abc123",
    "job_name": "my-workspace-trigger-0",
    "trigger_url": "https://my-app.calvinruntime.net/endpoint",
    "trigger_method": "POST",
    "timestamp": "2025-11-16T15:30:00.000Z",
    "status": "success",
    "duration_ms": 145,
    "http_status": 200,
    "retry_count": 0
  }
  ```

### Queue Storage (Redis)
- **Provider**: DigitalOcean Managed Redis
- **TLS**: Enabled (rediss://)
- **Data**: BullMQ jobs, schedules, job state
- **Retention**: Jobs removed on completion (max 100) or failure (max 1000)

---

## Deployment & Operations

### Deploying Platform Services

**kserve-api**:
```bash
# Build and push
cd kserve-api
docker build -t registry.digitalocean.com/calvin-apps/kserve-api:latest .
docker push registry.digitalocean.com/calvin-apps/kserve-api:latest

# Deploy (Knative)
kubectl apply -f k8s/rbac.yaml
kubectl apply -f k8s/deployment.yaml
```

**scheduler-api + scheduler-worker**:
```bash
# Build and push
cd scheduler-api
../build-and-push-do.sh scheduler-api latest

# Deploy
kubectl apply -f k8s/secret.yaml  # Update with real secrets first!
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/worker-deployment.yaml
kubectl apply -f k8s/domain-mapping.yaml
```

### Updating Platform Services

**Knative Services** (auto-rollout):
```bash
# Just push new image, Knative auto-updates
docker push registry.digitalocean.com/calvin-apps/kserve-api:latest
# Knative detects image change and creates new revision
```

**Regular Deployments** (manual rollout):
```bash
# Push new image
docker push registry.digitalocean.com/calvin-apps/scheduler-api:latest

# Restart deployment to pull new image
kubectl rollout restart deployment/scheduler-api
kubectl rollout restart deployment/scheduler-worker
```

---

## Common Operations

### View Customer Apps
```bash
# Via API
curl https://kserve-api.calvinruntime.net/models

# Via kubectl
kubectl get inferenceservices -n default
```

### View Scheduled Jobs
```bash
# Via API
curl https://scheduler-api.calvinruntime.net/api/workspaces/{workspace_id}/triggers

# Via Bull Board
open https://scheduler-api.calvinruntime.net/admin/queues
```

### View Metrics
```bash
# Via Dashboard
open https://scheduler-api.calvinruntime.net/metrics?workspace_id={workspace_id}

# Via API
curl https://scheduler-api.calvinruntime.net/metrics/api/{workspace_id}

# Direct S3 access
aws s3 ls s3://calvin-runtime-scheduler/metrics/ --recursive
```

### View Logs

**Customer app logs**:
```bash
# Via API
curl https://kserve-api.calvinruntime.net/logs/{app_name}?tail_lines=100

# Via kubectl
kubectl logs -l serving.kserve.io/inferenceservice={app_name} -c kserve-container
```

**Platform service logs**:
```bash
# scheduler-api
kubectl logs -l app=scheduler-api -f

# scheduler-worker
kubectl logs -l app=scheduler-worker -f

# kserve-api
kubectl logs -l serving.knative.dev/service=kserve-api -c api -f
```

---

## Why This Architecture?

### Why KServe for Customer Apps?
- ✅ Auto-scaling from 0 to 10 pods (saves resources)
- ✅ Scale-to-zero when apps are idle
- ✅ Automatic networking and SSL
- ✅ Clean URL management via DomainMapping
- ✅ Built-in health checks and readiness
- ✅ Revision management and rollbacks

### Why Knative is Required?
- KServe is **built on top of** Knative Serving
- InferenceService resources create Knative Services automatically
- Cannot remove Knative without breaking KServe
- Provides all the serverless features KServe needs

### Why Regular Deployment for Scheduler?
- ❌ Scheduler doesn't benefit from scale-to-zero (needs to always run)
- ❌ Background workers don't scale based on HTTP traffic
- ✅ Simpler deployment model for always-on services
- ✅ Less overhead (no Knative revisions)
- ✅ Easier to reason about (fixed 2 replicas)

### Why Not KServe for Platform Services?
- Platform services (kserve-api, scheduler-api) are infrastructure
- They should always be available (not scale to zero)
- kserve-api uses Knative but with min-scale: 1
- scheduler-api uses regular Deployment (even simpler)

---

## Quick Reference

### URLs
- **kserve-api**: https://kserve-api.calvinruntime.net
- **scheduler-api**: https://scheduler-api.calvinruntime.net
- **Metrics Dashboard**: https://scheduler-api.calvinruntime.net/metrics?workspace_id={id}
- **Queue Dashboard**: https://scheduler-api.calvinruntime.net/admin/queues
- **Customer Apps**: https://{app-name}.calvinruntime.net

### Repositories
- **GitHub**: https://github.com/goshops-com/kserve-api
- **Container Registry**: registry.digitalocean.com/calvin-apps/

### Resources
- **Redis**: DigitalOcean Managed Redis (TLS enabled)
- **S3**: DigitalOcean Spaces (calvin-runtime-scheduler bucket)
- **Kubernetes**: DigitalOcean Managed Kubernetes

---

## Troubleshooting

### Customer app won't start
1. Check InferenceService status: `kubectl get inferenceservice {name} -o yaml`
2. Check pod logs: `kubectl logs -l serving.kserve.io/inferenceservice={name}`
3. Verify image exists and is pullable
4. Check if app listens on port 8080

### Scheduled jobs not running
1. Check Bull Board: https://scheduler-api.calvinruntime.net/admin/queues
2. Check scheduler-worker logs: `kubectl logs -l app=scheduler-worker -f`
3. Verify Redis connection
4. Check workspace triggers exist: `GET /api/workspaces/{id}/triggers`

### Metrics not showing
1. Check S3 bucket for recent files
2. Check scheduler-worker logs for metrics writes
3. Verify workspace_id matches
4. Check S3 credentials in secret

### Service not accessible
1. Check DomainMapping: `kubectl get domainmapping`
2. Check Service exists: `kubectl get svc`
3. Check DNS resolves: `nslookup {service}.calvinruntime.net`
4. Check Kourier is running: `kubectl get pods -n kourier-system`
