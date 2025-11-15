#!/bin/bash

#############################################################
# Build and Push to DigitalOcean Container Registry
#
# This script builds a Docker image using the remote BuildKit
# and pushes it to DigitalOcean Container Registry
#############################################################

set -e

# Configuration
BUILDKIT_HOST="${BUILDKIT_HOST:-tcp://0.0.0.0:1234}"
DO_REGISTRY="registry.digitalocean.com"
DO_REPO="calvin-apps"

# Get parameters
IMAGE_NAME="${1:-myapp}"
VERSION="${2:-latest}"

# Full image reference
FULL_IMAGE="${DO_REGISTRY}/${DO_REPO}/${IMAGE_NAME}:${VERSION}"

echo "=============================================="
echo "  Building and Pushing to DigitalOcean"
echo "=============================================="
echo "Registry:  ${DO_REGISTRY}"
echo "Repo:      ${DO_REPO}"
echo "Image:     ${IMAGE_NAME}"
echo "Version:   ${VERSION}"
echo "Full tag:  ${FULL_IMAGE}"
echo "=============================================="
echo ""

# Check if logged in to DigitalOcean Container Registry
echo "🔐 Checking registry authentication..."
if ! grep -q "registry.digitalocean.com" ~/.docker/config.json 2>/dev/null; then
    echo "❌ Error: Not logged in to ${DO_REGISTRY}"
    echo ""
    echo "Please login first:"
    echo "  echo YOUR_TOKEN | docker login ${DO_REGISTRY} -u YOUR_EMAIL --password-stdin"
    echo ""
    exit 1
fi
echo "✓ Authenticated to ${DO_REGISTRY}"
echo ""

# Setup buildx builder (if not exists)
echo "🔧 Setting up remote builder..."
if ! docker buildx inspect remote-builder &>/dev/null; then
    docker buildx create --name remote-builder --driver remote ${BUILDKIT_HOST}
fi
docker buildx use remote-builder
echo ""

# Verify builder
echo "📊 Builder info:"
docker buildx inspect remote-builder | head -10
echo ""

# Build and push
echo "🚀 Building and pushing image..."
docker buildx build \
  --builder remote-builder \
  --push \
  -t ${FULL_IMAGE} \
  --build-arg BUILD_DATE=$(date -u +"%Y-%m-%dT%H:%M:%SZ") \
  --build-arg VERSION=${VERSION} \
  .

echo ""
echo "✅ Success!"
echo ""
echo "Image pushed to: ${FULL_IMAGE}"
echo ""
echo "To pull this image:"
echo "  docker pull ${FULL_IMAGE}"
echo ""
echo "To run this image:"
echo "  docker run --rm ${FULL_IMAGE}"
echo ""
