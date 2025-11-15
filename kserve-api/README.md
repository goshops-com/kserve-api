# KServe Model Management API

FastAPI-based service for managing KServe InferenceServices in Kubernetes.

## Features

- **Deploy models**: Create new KServe InferenceServices
- **Update models**: Update existing services (triggers restart)
- **Auto-restart**: Always pulls latest image with `imagePullPolicy: Always`
- **Environment variables**: Support for custom env vars per deployment
- **List models**: View all deployed models
- **Delete models**: Remove InferenceServices

## API Endpoints

### POST /deploy
Deploy or update a model.

**Request Body:**
```json
{
  "name": "my-model",
  "image": "registry.example.com/my-model:v1.0.0",
  "envs": {
    "MODEL_PATH": "/models",
    "LOG_LEVEL": "INFO"
  },
  "namespace": "default"
}
```

**Response:**
```json
{
  "name": "my-model",
  "namespace": "default",
  "action": "created",
  "status": "success",
  "url": "http://my-model.default.calvinruntime.net"
}
```

### GET /models?namespace=default
List all models in a namespace.

**Response:**
```json
{
  "models": [
    {
      "name": "my-model",
      "namespace": "default",
      "url": "http://my-model.default.calvinruntime.net",
      "ready": true
    }
  ],
  "count": 1
}
```

### GET /models/{namespace}/{name}
Get details of a specific model.

### DELETE /models/{namespace}/{name}
Delete a model.

### GET /health
Health check endpoint.

## Deployment Options

### Option 1: Knative Service (Recommended)
Provides auto-scaling and uses Knative for routing.

```bash
kubectl apply -f k8s/rbac.yaml
kubectl apply -f k8s/deployment.yaml
```

Access at: `http://kserve-api.default.calvinruntime.net`

### Option 2: Standard Deployment
Always-on deployment with regular Kubernetes Service.

```bash
kubectl apply -f k8s/rbac.yaml
kubectl apply -f k8s/deployment-standard.yaml
```

Access internally at: `http://kserve-api.default.svc.cluster.local`

## Building the Docker Image

```bash
# Build
docker build -t kserve-api:latest .

# Tag for registry
docker tag kserve-api:latest registry.digitalocean.com/YOUR_REGISTRY/kserve-api:latest

# Push
docker push registry.digitalocean.com/YOUR_REGISTRY/kserve-api:latest
```

## Testing Locally

```bash
# Install dependencies
pip install -r requirements.txt

# Run locally (requires kubeconfig)
python main.py
```

## Example Usage

### Deploy a new model
```bash
curl -X POST http://kserve-api.default.calvinruntime.net/deploy \
  -H "Content-Type: application/json" \
  -d '{
    "name": "sklearn-iris",
    "image": "kserve/sklearnserver:latest",
    "envs": {
      "STORAGE_URI": "gs://kfserving-examples/models/sklearn/1.0/model"
    }
  }'
```

### List all models
```bash
curl http://kserve-api.default.calvinruntime.net/models
```

### Get model details
```bash
curl http://kserve-api.default.calvinruntime.net/models/default/sklearn-iris
```

### Delete a model
```bash
curl -X DELETE http://kserve-api.default.calvinruntime.net/models/default/sklearn-iris
```

## Architecture

```
User Request
    |
    v
Cloudflare (SSL)
    |
    v
Kourier Ingress
    |
    v
KServe API (FastAPI)
    |
    v
Kubernetes API
    |
    v
KServe Controller
    |
    v
InferenceService (Model)
```

## Security

The API runs inside the cluster with a ServiceAccount that has permissions to:
- Create, read, update, delete InferenceServices
- Read ServingRuntimes and ClusterServingRuntimes
- Read namespaces

All operations are scoped to Kubernetes RBAC policies.
