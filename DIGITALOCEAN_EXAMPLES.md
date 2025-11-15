# DigitalOcean Container Registry - Quick Reference

## Login

```bash
echo "YOUR_DO_TOKEN" | \
  docker login registry.digitalocean.com -u YOUR_EMAIL --password-stdin
```

## Build and Push Examples

### Single Tag
```bash
docker buildx build \
  --builder remote-builder \
  --push \
  -t registry.digitalocean.com/calvin-apps/myapp:latest \
  .
```

### Multiple Tags (latest + version)
```bash
docker buildx build \
  --builder remote-builder \
  --push \
  -t registry.digitalocean.com/calvin-apps/myapp:latest \
  -t registry.digitalocean.com/calvin-apps/myapp:v1.0.0 \
  .
```

### With Git Commit Hash
```bash
GIT_COMMIT=$(git rev-parse --short HEAD)

docker buildx build \
  --builder remote-builder \
  --push \
  -t registry.digitalocean.com/calvin-apps/myapp:${GIT_COMMIT} \
  -t registry.digitalocean.com/calvin-apps/myapp:latest \
  .
```

### With Build Arguments
```bash
docker buildx build \
  --builder remote-builder \
  --push \
  --build-arg VERSION=1.0.0 \
  --build-arg BUILD_DATE=$(date -u +"%Y-%m-%dT%H:%M:%SZ") \
  -t registry.digitalocean.com/calvin-apps/myapp:1.0.0 \
  .
```

### Production + Staging Tags
```bash
# For production
docker buildx build \
  --builder remote-builder \
  --push \
  -t registry.digitalocean.com/calvin-apps/myapp:prod \
  -t registry.digitalocean.com/calvin-apps/myapp:prod-v1.0.0 \
  .

# For staging
docker buildx build \
  --builder remote-builder \
  --push \
  -t registry.digitalocean.com/calvin-apps/myapp:staging \
  -t registry.digitalocean.com/calvin-apps/myapp:staging-v1.0.0 \
  .
```

### Multiple Images in Same Repo
```bash
# Frontend
docker buildx build \
  --builder remote-builder \
  --push \
  -f Dockerfile.frontend \
  -t registry.digitalocean.com/calvin-apps/frontend:latest \
  .

# Backend
docker buildx build \
  --builder remote-builder \
  --push \
  -f Dockerfile.backend \
  -t registry.digitalocean.com/calvin-apps/backend:latest \
  .

# Worker
docker buildx build \
  --builder remote-builder \
  --push \
  -f Dockerfile.worker \
  -t registry.digitalocean.com/calvin-apps/worker:latest \
  .
```

## Using the Build Script

The `build-and-push-do.sh` script simplifies the build process:

```bash
# Build with default name (myapp) and tag (latest)
./build-and-push-do.sh

# Build with custom image name
./build-and-push-do.sh frontend

# Build with custom image name and version
./build-and-push-do.sh backend v1.2.3
```

## Pulling Images

After pushing, you can pull from any machine:

```bash
# Login first
echo "YOUR_DO_TOKEN" | \
  docker login registry.digitalocean.com -u YOUR_EMAIL --password-stdin

# Pull the image
docker pull registry.digitalocean.com/calvin-apps/myapp:latest

# Run it
docker run --rm registry.digitalocean.com/calvin-apps/myapp:latest
```

## Registry Cache (Speed Up Builds)

Use registry cache to speed up builds across different machines:

```bash
docker buildx build \
  --builder remote-builder \
  --cache-from=type=registry,ref=registry.digitalocean.com/calvin-apps/myapp:buildcache \
  --cache-to=type=registry,ref=registry.digitalocean.com/calvin-apps/myapp:buildcache,mode=max \
  --push \
  -t registry.digitalocean.com/calvin-apps/myapp:latest \
  .
```

## GitHub Actions Integration

Example GitHub Actions workflow:

```yaml
name: Build and Push

on:
  push:
    branches: [main]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Login to DigitalOcean Registry
        run: |
          echo "${{ secrets.DO_REGISTRY_TOKEN }}" | \
            docker login registry.digitalocean.com \
            -u ${{ secrets.DO_REGISTRY_EMAIL }} \
            --password-stdin

      - name: Setup Buildx
        run: |
          docker buildx create \
            --name remote-builder \
            --driver remote \
            tcp://${{ secrets.BUILDKIT_HOST }}:1234
          docker buildx use remote-builder

      - name: Build and Push
        run: |
          docker buildx build \
            --push \
            -t registry.digitalocean.com/calvin-apps/myapp:${{ github.sha }} \
            -t registry.digitalocean.com/calvin-apps/myapp:latest \
            .
```

## Viewing Images in DigitalOcean

1. Go to: https://cloud.digitalocean.com/registry
2. Navigate to your `calvin-apps` repository
3. View all pushed images and tags

## Deleting Old Images

Use DigitalOcean CLI (doctl):

```bash
# Install doctl
brew install doctl  # macOS
# or
snap install doctl  # Linux

# Authenticate
doctl auth init

# List images
doctl registry repository list-tags calvin-apps myapp

# Delete a specific tag
doctl registry repository delete-tag calvin-apps myapp old-tag
```
