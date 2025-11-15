#!/bin/bash
# DigitalOcean Container Registry Login

echo "YOUR_DO_TOKEN" | docker login registry.digitalocean.com -u YOUR_EMAIL --password-stdin
