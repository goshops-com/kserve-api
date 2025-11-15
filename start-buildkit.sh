#!/bin/bash

set -e

echo "🔧 Starting BuildKit with persistent cache..."
echo ""

# Check if docker-compose is available
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo "❌ Error: docker-compose is not installed"
    exit 1
fi

# Determine which compose command to use
if docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
else
    COMPOSE_CMD="docker-compose"
fi

# Start BuildKit
echo "📦 Starting buildkitd container..."
$COMPOSE_CMD up -d

echo ""
echo "✅ BuildKit is running!"
echo ""
echo "📊 Service Information:"
echo "  - Container: buildkitd"
echo "  - Port: 1234"
echo "  - Cache Volume: buildkit-cache"
echo "  - Cache Location: /var/lib/buildkit"
echo ""
echo "🔗 To connect to this BuildKit instance:"
echo "  export BUILDKIT_HOST=tcp://0.0.0.0:1234"
echo ""
echo "📝 Useful commands:"
echo "  View logs:        $COMPOSE_CMD logs -f buildkitd"
echo "  Stop service:     $COMPOSE_CMD stop"
echo "  Restart service:  $COMPOSE_CMD restart"
echo "  Remove service:   $COMPOSE_CMD down"
echo "  View volume:      docker volume inspect buildkit-cache"
echo ""
