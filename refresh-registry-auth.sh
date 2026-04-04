#!/bin/bash
# Refresh DigitalOcean registry auth for BuildKit
TOKEN=$(cat /root/.doctl_token | tr -d '\n')
AUTH=$(echo -n "sjcotto@gmail.com:${TOKEN}" | base64 -w0)

cat > /root/buildkit-config/config.json << CONF
{
  "auths": {
    "registry.digitalocean.com": {
      "auth": "${AUTH}"
    }
  }
}
CONF

# Also refresh docker login for local builds
echo "${TOKEN}" | docker login registry.digitalocean.com -u sjcotto@gmail.com --password-stdin >/dev/null 2>&1

# Restart BuildKit to pick up new creds
docker restart buildkitd >/dev/null 2>&1

echo "$(date): Registry auth refreshed"
