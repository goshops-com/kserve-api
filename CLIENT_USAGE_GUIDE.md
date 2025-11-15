# How to Build and Push Using Remote BuildKit

## How It Works

When you build with the remote BuildKit:
1. **Client** (your machine) - Sends Dockerfile, context, and credentials
2. **BuildKit Server** (remote) - Does the heavy lifting (build + push)
3. **Registry** (DigitalOcean) - Receives the final image

**Key Point**: Credentials stay on YOUR machine and are securely sent to BuildKit only for that build operation.

---

## Client Setup (One-Time)

### Step 1: Install Docker (for buildx CLI only)

```bash
# The client only needs Docker CLI, not the daemon
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
```

### Step 2: Connect to Remote BuildKit

```bash
# Replace YOUR_BUILDKIT_HOST with the server IP/hostname
docker buildx create \
  --name remote-builder \
  --driver remote \
  tcp://YOUR_BUILDKIT_HOST:1234

# Set it as default
docker buildx use remote-builder

# Verify connection
docker buildx inspect remote-builder
```

**Example:**
```bash
docker buildx create --name remote-builder --driver remote tcp://192.168.1.100:1234
docker buildx use remote-builder
```

---

## Building and Pushing Images

### Step 1: Login to Registry

```bash
# Login to DigitalOcean Container Registry
echo "YOUR_DO_TOKEN" | \
  docker login registry.digitalocean.com -u YOUR_EMAIL --password-stdin
```

**For DigitalOcean (calvin-apps repo):**
```bash
echo "YOUR_DO_TOKEN" | \
  docker login registry.digitalocean.com -u YOUR_EMAIL --password-stdin
```

### Step 2: Build and Push

```bash
# Navigate to your project directory
cd /path/to/your/project

# Build and push
docker buildx build \
  --push \
  -t registry.digitalocean.com/calvin-apps/YOUR_APP:YOUR_TAG \
  .
```

**Examples:**

```bash
# Simple single tag
docker buildx build \
  --push \
  -t registry.digitalocean.com/calvin-apps/myapp:latest \
  .

# Multiple tags
docker buildx build \
  --push \
  -t registry.digitalocean.com/calvin-apps/myapp:latest \
  -t registry.digitalocean.com/calvin-apps/myapp:v1.2.3 \
  -t registry.digitalocean.com/calvin-apps/myapp:prod \
  .

# With build arguments
docker buildx build \
  --push \
  --build-arg VERSION=1.2.3 \
  -t registry.digitalocean.com/calvin-apps/myapp:1.2.3 \
  .
```

---

## Complete Workflow Example

```bash
# 1. Setup (one-time)
docker buildx create --name remote-builder --driver remote tcp://192.168.1.100:1234
docker buildx use remote-builder

# 2. Login to registry (once per session)
echo "YOUR_TOKEN" | docker login registry.digitalocean.com -u YOUR_EMAIL --password-stdin

# 3. Build and push (repeat as needed)
cd ~/my-app
docker buildx build --push -t registry.digitalocean.com/calvin-apps/my-app:v1.0.0 .
```

---

## Why This Approach?

### Benefits:
- ✅ **No heavy lifting on client** - BuildKit server does all the work
- ✅ **Persistent cache** - Builds are fast after the first one
- ✅ **Secure** - Credentials never stored on the server
- ✅ **Scalable** - Multiple developers use the same BuildKit
- ✅ **Consistent** - Same build environment for everyone

### Security:
- Credentials are sent securely over the connection
- They're used only for that specific build
- They're never stored on the BuildKit server
- Each client manages their own credentials

---

## Troubleshooting

### "Cannot connect to BuildKit"
```bash
# Check if BuildKit server is running
docker buildx inspect remote-builder

# Try recreating the builder
docker buildx rm remote-builder
docker buildx create --name remote-builder --driver remote tcp://YOUR_HOST:1234
docker buildx use remote-builder
```

### "Unauthorized" Error
```bash
# Make sure you're logged in
docker login registry.digitalocean.com

# Check your credentials
cat ~/.docker/config.json
```

### "Connection Refused"
- Verify the BuildKit server is running: `docker ps | grep buildkitd`
- Check firewall allows port 1234
- Verify the host IP is correct

---

## Different Registries

### Docker Hub
```bash
docker login
docker buildx build --push -t YOUR_USERNAME/image:tag .
```

### GitHub Container Registry (GHCR)
```bash
echo "YOUR_PAT" | docker login ghcr.io -u YOUR_USERNAME --password-stdin
docker buildx build --push -t ghcr.io/YOUR_USERNAME/image:tag .
```

### AWS ECR
```bash
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin \
  123456789.dkr.ecr.us-east-1.amazonaws.com

docker buildx build --push -t 123456789.dkr.ecr.us-east-1.amazonaws.com/image:tag .
```

### Google GCR
```bash
gcloud auth configure-docker
docker buildx build --push -t gcr.io/PROJECT_ID/image:tag .
```

---

## Quick Reference

| Task | Command |
|------|---------|
| Setup builder | `docker buildx create --name remote-builder --driver remote tcp://HOST:1234` |
| Use builder | `docker buildx use remote-builder` |
| Login DO | `echo "TOKEN" \| docker login registry.digitalocean.com -u EMAIL --password-stdin` |
| Build & Push | `docker buildx build --push -t registry.digitalocean.com/calvin-apps/APP:TAG .` |
| List builders | `docker buildx ls` |
| Inspect builder | `docker buildx inspect remote-builder` |
| Remove builder | `docker buildx rm remote-builder` |

---

## Next Steps

Once your image is pushed:

```bash
# Pull and run from any server
docker pull registry.digitalocean.com/calvin-apps/myapp:latest
docker run -d registry.digitalocean.com/calvin-apps/myapp:latest
```

View your images: https://cloud.digitalocean.com/registry
