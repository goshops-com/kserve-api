#!/bin/bash
#############################################################
# Test Remote BuildKit from Another Server
#
# Run this on ANY other server to test the remote build
#############################################################

set -e

echo "================================================"
echo "  Remote BuildKit Test"
echo "================================================"
echo ""

# Configuration
BUILDKIT_SERVER="68.183.49.201"
BUILDKIT_PORT="1234"
DO_REGISTRY="registry.digitalocean.com"
DO_EMAIL="YOUR_EMAIL"
DO_TOKEN="YOUR_DO_TOKEN"

echo "📋 Configuration:"
echo "  BuildKit Server: ${BUILDKIT_SERVER}:${BUILDKIT_PORT}"
echo "  Registry: ${DO_REGISTRY}"
echo ""

# Step 1: Install Docker if needed
echo "1️⃣  Checking Docker installation..."
if ! command -v docker &> /dev/null; then
    echo "Docker not found. Installing..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    echo "✓ Docker installed"
else
    echo "✓ Docker already installed"
fi
echo ""

# Step 2: Setup remote builder
echo "2️⃣  Setting up remote builder connection..."
docker buildx rm remote-builder 2>/dev/null || true
docker buildx create \
  --name remote-builder \
  --driver remote \
  tcp://${BUILDKIT_SERVER}:${BUILDKIT_PORT}

docker buildx use remote-builder
echo "✓ Remote builder connected"
echo ""

# Step 3: Test connection
echo "3️⃣  Testing connection to BuildKit server..."
docker buildx inspect remote-builder
echo "✓ Connection successful"
echo ""

# Step 4: Login to registry
echo "4️⃣  Logging in to DigitalOcean registry..."
echo "${DO_TOKEN}" | docker login ${DO_REGISTRY} -u ${DO_EMAIL} --password-stdin
echo "✓ Logged in to registry"
echo ""

# Step 5: Create test Dockerfile
echo "5️⃣  Creating test application..."
mkdir -p /tmp/buildkit-test
cd /tmp/buildkit-test

cat > Dockerfile <<'EOF'
FROM alpine:latest

RUN apk add --no-cache curl

RUN echo "Remote BuildKit Test - Built on $(date)" > /tmp/test.txt

CMD ["sh", "-c", "cat /tmp/test.txt && echo 'Remote build successful!'"]
EOF

cat > .dockerignore <<'EOF'
.git
*.md
EOF

echo "✓ Test Dockerfile created"
echo ""

# Step 6: Build and push
echo "6️⃣  Building and pushing to registry..."
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
IMAGE_TAG="registry.digitalocean.com/calvin-apps/remote-test:${TIMESTAMP}"

echo "Image: ${IMAGE_TAG}"
docker buildx build \
  --push \
  -t ${IMAGE_TAG} \
  -t registry.digitalocean.com/calvin-apps/remote-test:latest \
  .

echo ""
echo "✓ Build and push successful!"
echo ""

# Step 7: Verify
echo "7️⃣  Verifying pushed image..."
docker pull ${IMAGE_TAG}
docker run --rm ${IMAGE_TAG}
echo ""

echo "================================================"
echo "  ✅ SUCCESS! Remote BuildKit is working!"
echo "================================================"
echo ""
echo "Your image is available at:"
echo "  ${IMAGE_TAG}"
echo ""
echo "View in DigitalOcean:"
echo "  https://cloud.digitalocean.com/registry"
echo ""
