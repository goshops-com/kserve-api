# BuildKit Client Usage Guide

## Table of Contents
1. [Setup Client Connection](#setup-client-connection)
2. [Build and Push to Docker Hub](#build-and-push-to-docker-hub)
3. [Build and Push to GitHub Container Registry](#build-and-push-to-github-container-registry)
4. [Build and Push to Private Registry](#build-and-push-to-private-registry)
5. [Multi-platform Builds](#multi-platform-builds)
6. [Advanced Tagging Strategies](#advanced-tagging-strategies)

---

## Setup Client Connection

### Option 1: Using Buildx Builder (Recommended)

```bash
# Create a builder pointing to the remote BuildKit
docker buildx create \
  --name remote-builder \
  --driver remote \
  tcp://YOUR_BUILDKIT_HOST:1234

# Set as default builder
docker buildx use remote-builder

# Verify connection
docker buildx inspect remote-builder
```

### Option 2: Using Environment Variable

```bash
# Set BuildKit host
export BUILDKIT_HOST=tcp://YOUR_BUILDKIT_HOST:1234

# Use buildctl directly
buildctl build --help
```

---

## Build and Push to Docker Hub

### Prerequisites
```bash
# Login to Docker Hub
docker login

# Or specify credentials
docker login -u YOUR_USERNAME -p YOUR_PASSWORD
```

### Single Tag
```bash
docker buildx build \
  --builder remote-builder \
  --push \
  -t YOUR_USERNAME/image-name:tag \
  .
```

### Multiple Tags
```bash
docker buildx build \
  --builder remote-builder \
  --push \
  -t YOUR_USERNAME/image-name:latest \
  -t YOUR_USERNAME/image-name:v1.0.0 \
  -t YOUR_USERNAME/image-name:stable \
  .
```

### Example
```bash
docker buildx build \
  --builder remote-builder \
  --push \
  -t johndoe/myapp:latest \
  -t johndoe/myapp:1.2.3 \
  .
```

---

## Build and Push to GitHub Container Registry

### Prerequisites
```bash
# Create GitHub Personal Access Token with write:packages scope
# https://github.com/settings/tokens

# Login to GHCR
echo YOUR_PAT | docker login ghcr.io -u YOUR_GITHUB_USERNAME --password-stdin
```

### Build and Push
```bash
docker buildx build \
  --builder remote-builder \
  --push \
  -t ghcr.io/YOUR_GITHUB_USERNAME/image-name:tag \
  .
```

### Example
```bash
docker buildx build \
  --builder remote-builder \
  --push \
  -t ghcr.io/octocat/myapp:latest \
  -t ghcr.io/octocat/myapp:v1.0.0 \
  .
```

---

## Build and Push to Private Registry

### Prerequisites
```bash
# Login to your private registry
docker login registry.example.com -u USERNAME -p PASSWORD
```

### Build and Push
```bash
docker buildx build \
  --builder remote-builder \
  --push \
  -t registry.example.com/namespace/image-name:tag \
  .
```

### Examples

**AWS ECR**
```bash
# Login to ECR
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin \
  123456789.dkr.ecr.us-east-1.amazonaws.com

# Build and push
docker buildx build \
  --builder remote-builder \
  --push \
  -t 123456789.dkr.ecr.us-east-1.amazonaws.com/myapp:latest \
  .
```

**Google Container Registry (GCR)**
```bash
# Login to GCR
gcloud auth configure-docker

# Build and push
docker buildx build \
  --builder remote-builder \
  --push \
  -t gcr.io/PROJECT_ID/myapp:latest \
  .
```

**Azure Container Registry (ACR)**
```bash
# Login to ACR
az acr login --name myregistry

# Build and push
docker buildx build \
  --builder remote-builder \
  --push \
  -t myregistry.azurecr.io/myapp:latest \
  .
```

**Harbor**
```bash
# Login to Harbor
docker login harbor.example.com -u admin

# Build and push
docker buildx build \
  --builder remote-builder \
  --push \
  -t harbor.example.com/library/myapp:latest \
  .
```

---

## Multi-platform Builds

Build for multiple architectures and push to registry:

```bash
docker buildx build \
  --builder remote-builder \
  --platform linux/amd64,linux/arm64,linux/arm/v7 \
  --push \
  -t YOUR_USERNAME/image-name:latest \
  .
```

**Note**: Multi-platform builds require QEMU or native builders for each platform.

---

## Advanced Tagging Strategies

### Git-based Tagging
```bash
# Get git commit hash and branch
GIT_COMMIT=$(git rev-parse --short HEAD)
GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD)

docker buildx build \
  --builder remote-builder \
  --push \
  -t registry.example.com/myapp:${GIT_BRANCH}-${GIT_COMMIT} \
  -t registry.example.com/myapp:latest \
  .
```

### Semantic Versioning
```bash
VERSION="1.2.3"
MAJOR=$(echo $VERSION | cut -d. -f1)
MINOR=$(echo $VERSION | cut -d. -f1-2)

docker buildx build \
  --builder remote-builder \
  --push \
  -t registry.example.com/myapp:${VERSION} \
  -t registry.example.com/myapp:${MINOR} \
  -t registry.example.com/myapp:${MAJOR} \
  -t registry.example.com/myapp:latest \
  .
```

### Timestamp-based Tagging
```bash
TIMESTAMP=$(date +%Y%m%d-%H%M%S)

docker buildx build \
  --builder remote-builder \
  --push \
  -t registry.example.com/myapp:${TIMESTAMP} \
  -t registry.example.com/myapp:latest \
  .
```

### CI/CD Tagging (GitHub Actions example)
```bash
# Using GitHub Actions environment variables
docker buildx build \
  --builder remote-builder \
  --push \
  -t registry.example.com/myapp:${GITHUB_SHA} \
  -t registry.example.com/myapp:${GITHUB_REF_NAME} \
  .
```

---

## Build Arguments and Secrets

### Build Arguments
```bash
docker buildx build \
  --builder remote-builder \
  --build-arg VERSION=1.2.3 \
  --build-arg BUILD_DATE=$(date -u +"%Y-%m-%dT%H:%M:%SZ") \
  --push \
  -t registry.example.com/myapp:latest \
  .
```

### Secrets (for private dependencies, keys, etc.)
```bash
docker buildx build \
  --builder remote-builder \
  --secret id=github_token,src=$HOME/.github_token \
  --push \
  -t registry.example.com/myapp:latest \
  .
```

In Dockerfile:
```dockerfile
# syntax=docker/dockerfile:1
RUN --mount=type=secret,id=github_token \
    TOKEN=$(cat /run/secrets/github_token) && \
    git clone https://${TOKEN}@github.com/private/repo.git
```

---

## Cache Strategies for Faster Builds

### Using Registry Cache
```bash
docker buildx build \
  --builder remote-builder \
  --cache-from=type=registry,ref=registry.example.com/myapp:cache \
  --cache-to=type=registry,ref=registry.example.com/myapp:cache,mode=max \
  --push \
  -t registry.example.com/myapp:latest \
  .
```

### Using Local Cache (on BuildKit server)
The buildkitd instance already has persistent local cache via the volume mount,
so subsequent builds automatically benefit from layer caching.

---

## Troubleshooting

### Authentication Issues
```bash
# Verify you're logged in
cat ~/.docker/config.json

# Re-login if needed
docker logout registry.example.com
docker login registry.example.com
```

### Check Builder Status
```bash
docker buildx ls
docker buildx inspect remote-builder
```

### View BuildKit Logs
```bash
# On the server where buildkitd is running
docker logs buildkitd -f
```

### Test Connection
```bash
# Simple build without push
docker buildx build \
  --builder remote-builder \
  -t test:latest \
  .
```

---

## Complete Example Script

```bash
#!/bin/bash
set -e

# Configuration
REGISTRY="docker.io"
USERNAME="johndoe"
IMAGE_NAME="myapp"
VERSION="1.2.3"
BUILDKIT_HOST="tcp://buildkit.example.com:1234"

# Setup
echo "Setting up builder..."
docker buildx create --name remote-builder --driver remote ${BUILDKIT_HOST} || true
docker buildx use remote-builder

# Login
echo "Logging in to registry..."
docker login ${REGISTRY} -u ${USERNAME}

# Build and push
echo "Building and pushing..."
docker buildx build \
  --builder remote-builder \
  --push \
  -t ${REGISTRY}/${USERNAME}/${IMAGE_NAME}:${VERSION} \
  -t ${REGISTRY}/${USERNAME}/${IMAGE_NAME}:latest \
  --build-arg VERSION=${VERSION} \
  --build-arg BUILD_DATE=$(date -u +"%Y-%m-%dT%H:%M:%SZ") \
  .

echo "Build complete!"
echo "Image pushed to: ${REGISTRY}/${USERNAME}/${IMAGE_NAME}:${VERSION}"
```
