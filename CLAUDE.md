# CalvinCode Runtime Platform

## Repository Structure

```
/root
├── kserve-api/          # Deployment API (FastAPI) - manages Knative services
│   └── main.py          # Single file: deploy, logs, streaming, app management
├── scheduler-api/       # Scheduler + Metrics (Node.js/Express + BullMQ)
│   └── src/
│       ├── app.js                          # Express app + debug endpoints
│       ├── routes/metrics.routes.js        # Metrics API + next execution time
│       ├── views/metrics-dashboard.html    # Metrics UI dashboard
│       ├── services/metrics.service.js     # Write metrics to S3 (by workspace)
│       ├── services/metrics-query.service.js # Query metrics from S3
│       ├── workers/trigger.worker.js       # BullMQ job executor
│       └── queue/trigger.queue.js          # BullMQ queue config
├── metrics-collector/   # Python CronJob for Knative usage metrics
├── build-and-push-do.sh # Build & push images via remote BuildKit
└── start-buildkit.sh    # Start BuildKit daemon
```

## Services & URLs

| Service | URL | Tech |
|---------|-----|------|
| kserve-api | kserve-api.calvinruntime.net | Python FastAPI |
| scheduler-api | scheduler-api.calvinruntime.net | Node.js Express + BullMQ |
| Customer apps | {name}.calvinruntime.net | Knative |

## Build & Deploy

```bash
# Build and push image
./build-and-push-do.sh {service-name} latest

# Trigger new Knative revision
kubectl patch ksvc {name} -n default --type='json' \
  -p='[{"op":"replace","path":"/spec/template/metadata/annotations/client.knative.dev~1updateTimestamp","value":"'$(date -u +%Y-%m-%dT%H:%M:%SZ)'"}]'
```

## Infrastructure

- **Cloud:** DigitalOcean (K8s + Spaces + Container Registry)
- **K8s namespace:** default
- **Registry:** registry.digitalocean.com/calvin-apps/
- **S3 bucket:** calvin-runtime-scheduler
- **S3 metrics path:** metrics/workspace={id}/year/month/day/hour/

## Deployment API Sizes

| Size | CPU | RAM |
|:----:|:---:|:---:|
| sm | 0.5 | 512 MB |
| md | 1 | 1 GB |
| lg | 1 | 2 GB |
| xl | 2 | 4 GB |

## Always-on (min-scale)

`POST /deploy` accepts two optional fields; with neither, the app scales to zero as before.

| Field | Effect |
|-------|--------|
| `always_on: true` | `min-scale: 1` permanently |
| `always_on_schedule: {start, end, timezone, days?}` | `min-scale: 1` only inside the window (`HH:MM`, IANA timezone, `days` 0=Sunday..6, `end < start` crosses midnight) |

- The setting is stored on the Knative Service as `calvincode.net/always-on-mode` / `calvincode.net/always-on-schedule` annotations.
- Knative has no native schedule, so `POST /always-on/reconcile` sets `min-scale` to what it should be right now. It is idempotent and only touches apps carrying the annotation.
- The scheduler calls it every minute: a trigger registered under workspace `calvin-always-on` (env `prod`) in scheduler-api. If schedules stop being applied, check that trigger still exists:
  `curl https://scheduler-api.calvinruntime.net/api/workspaces/calvin-always-on/triggers`
- Changing `min-scale` creates a new revision, so the pod is replaced when a window opens and closes.

## Important Notes

- Never commit files with secrets (.doctl_token, .git-credentials, docker-login.sh)
- GitHub push protection is enabled - will reject commits containing tokens
- Knative pods have 2 containers: `user-container` (app) and `queue-proxy` (Knative sidecar)
- Always specify `container="user-container"` when reading pod logs
- scheduler-worker runs as a regular K8s Deployment (not Knative)
