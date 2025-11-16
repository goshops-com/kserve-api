# Kubernetes Deployment Guide

This guide covers deploying the Scheduler API to Kubernetes (DigitalOcean Kubernetes or any K8s cluster).

## Prerequisites

- Kubernetes cluster up and running
- `kubectl` configured to access your cluster
- Docker registry access (DigitalOcean Container Registry or Docker Hub)
- Redis instance (managed Redis or deployed in K8s)

## Step 1: Build and Push Docker Image

### Using DigitalOcean Container Registry

```bash
# Login to DigitalOcean registry
echo "YOUR_DO_TOKEN" | docker login registry.digitalocean.com -u YOUR_EMAIL --password-stdin

# Build the image
docker build -t registry.digitalocean.com/YOUR_REGISTRY/scheduler-api:latest .

# Push to registry
docker push registry.digitalocean.com/YOUR_REGISTRY/scheduler-api:latest
```

### Using BuildKit (Remote Builder)

```bash
# If using remote BuildKit server
docker buildx build \
  --builder remote-builder \
  --platform linux/amd64 \
  --push \
  -t registry.digitalocean.com/YOUR_REGISTRY/scheduler-api:latest \
  .
```

## Step 2: Configure Redis URL

Edit `k8s/secret.yaml` and update the Redis URL:

```yaml
stringData:
  REDIS_URL: "redis://your-redis-host:6379"
  # For Redis with password:
  # REDIS_URL: "redis://:your-password@your-redis-host:6379/0"
  # For managed Redis (e.g., DigitalOcean):
  # REDIS_URL: "rediss://default:password@host:25061/0"
```

## Step 3: Update Image Registry

Update the image path in the deployment files:

**k8s/api-deployment.yaml:**
```yaml
image: registry.digitalocean.com/YOUR_REGISTRY/scheduler-api:latest
```

**k8s/worker-deployment.yaml:**
```yaml
image: registry.digitalocean.com/YOUR_REGISTRY/scheduler-api:latest
```

## Step 4: Create Image Pull Secret

If using a private registry:

```bash
kubectl create secret docker-registry registry-secret \
  --docker-server=registry.digitalocean.com \
  --docker-username=YOUR_EMAIL \
  --docker-password=YOUR_DO_TOKEN
```

## Step 5: Deploy to Kubernetes

```bash
# Apply the secret first
kubectl apply -f k8s/secret.yaml

# Deploy the API and Worker
kubectl apply -f k8s/api-deployment.yaml
kubectl apply -f k8s/worker-deployment.yaml

# Create the service
kubectl apply -f k8s/service.yaml
```

## Step 6: Verify Deployment

```bash
# Check pods
kubectl get pods -l app=scheduler-api

# Check deployments
kubectl get deployments

# Check services
kubectl get services

# View API logs
kubectl logs -l app=scheduler-api,component=api --tail=50

# View worker logs
kubectl logs -l app=scheduler-api,component=worker --tail=50
```

## Step 7: Get External IP

```bash
# Get the LoadBalancer IP
kubectl get service scheduler-api-loadbalancer

# Wait for EXTERNAL-IP to be assigned
```

## Step 8: Test the API

```bash
# Get the external IP
EXTERNAL_IP=$(kubectl get service scheduler-api-loadbalancer -o jsonpath='{.status.loadBalancer.ingress[0].ip}')

# Test health endpoint
curl http://$EXTERNAL_IP/health

# Create a workspace trigger
curl -X POST http://$EXTERNAL_IP/api/workspaces/test-workspace/triggers \
  -H "Content-Type: application/json" \
  -d @example-request.json
```

## Scaling

### Scale API Replicas

```bash
kubectl scale deployment scheduler-api --replicas=3
```

### Scale Worker Replicas

```bash
kubectl scale deployment scheduler-worker --replicas=2
```

## Monitoring

### View Logs in Real-time

```bash
# API logs
kubectl logs -f deployment/scheduler-api

# Worker logs
kubectl logs -f deployment/scheduler-worker
```

### Check Pod Status

```bash
kubectl describe pod -l app=scheduler-api
```

## Troubleshooting

### Pod Not Starting

```bash
kubectl describe pod <pod-name>
kubectl logs <pod-name>
```

### Connection Issues

```bash
# Check if secret is created
kubectl get secret scheduler-secrets

# Check secret values (be careful in production!)
kubectl get secret scheduler-secrets -o yaml
```

### Redis Connection

```bash
# Exec into pod to test Redis connection
kubectl exec -it deployment/scheduler-api -- sh

# Inside the pod
apk add redis
redis-cli -u $REDIS_URL ping
```

## Clean Up

```bash
# Delete all resources
kubectl delete -f k8s/
kubectl delete secret registry-secret
```

## Using with Ingress (Optional)

If you prefer to use Ingress instead of LoadBalancer:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: scheduler-api-ingress
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  rules:
  - host: scheduler-api.yourdomain.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: scheduler-api
            port:
              number: 80
  tls:
  - hosts:
    - scheduler-api.yourdomain.com
    secretName: scheduler-api-tls
```

## Production Considerations

1. **Redis**: Use a managed Redis service (DigitalOcean, AWS ElastiCache, etc.)
2. **Monitoring**: Set up Prometheus/Grafana for monitoring
3. **Logging**: Use centralized logging (ELK stack, Loki, etc.)
4. **Secrets**: Use external secrets management (Vault, Sealed Secrets)
5. **Resource Limits**: Adjust based on your workload
6. **Auto-scaling**: Configure HPA (Horizontal Pod Autoscaler)
7. **Backup**: Regular backups of Redis data
