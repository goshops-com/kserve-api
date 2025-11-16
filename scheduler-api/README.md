# Scheduler API

A BullMQ-based scheduler system for managing cron jobs and HTTP requests per workspace.

## Features

- Schedule HTTP requests using cron expressions
- Manage triggers per workspace
- Automatic job removal and recreation
- Built with BullMQ for reliable job processing
- RESTful API with Express

## Project Structure

```
scheduler-api/
├── src/
│   ├── config/           # Configuration files
│   │   ├── app.js       # App configuration
│   │   └── redis.js     # Redis connection setup
│   ├── queue/           # BullMQ queue definitions
│   │   └── trigger.queue.js
│   ├── workers/         # BullMQ workers
│   │   └── trigger.worker.js
│   ├── services/        # Business logic
│   │   └── workspace.service.js
│   ├── routes/          # API routes
│   │   └── workspace.routes.js
│   ├── app.js           # Express app setup
│   └── index.js         # Application entry point
├── package.json
├── .env.example
└── README.md
```

## Quick Start

### Local Development

1. **Install dependencies:**

```bash
npm install
```

2. **Configure environment:**

Copy `.env.example` to `.env` and configure:

```bash
PORT=3000
NODE_ENV=development
REDIS_URL=redis://localhost:6379
```

### Kubernetes Deployment

See [DEPLOYMENT.md](./DEPLOYMENT.md) for complete Kubernetes deployment instructions including:
- Building and pushing Docker images
- Deploying to DigitalOcean Kubernetes
- Setting up Redis
- Scaling and monitoring

## Usage

### Start the API Server

```bash
npm start
```

For development with auto-reload:
```bash
npm run dev
```

### Start the Worker

In a separate terminal:
```bash
npm run worker
```

## API Endpoints

### Update Workspace Triggers

**POST** `/api/workspaces/:workspace_id/triggers`

Removes all existing triggers for the workspace and creates new ones.

**Request Body:**
```json
{
  "triggers": [
    {
      "cron": "0 */2 * * *",
      "url": "https://api.example.com/webhook",
      "method": "POST",
      "payload": {
        "event": "scheduled_task",
        "data": {}
      },
      "headers": {
        "Authorization": "Bearer YOUR_TOKEN",
        "Content-Type": "application/json"
      }
    },
    {
      "cron": "0 9 * * 1-5",
      "url": "https://api.example.com/report",
      "method": "GET",
      "headers": {
        "X-API-Key": "YOUR_API_KEY"
      }
    }
  ]
}
```

**Response:**
```json
{
  "success": true,
  "workspace_id": "workspace-123",
  "removed": 2,
  "added": 2,
  "jobs": [
    {
      "jobId": "workspace-123:0",
      "jobName": "workspace-123-trigger-0",
      "cron": "0 */2 * * *",
      "url": "https://api.example.com/webhook",
      "method": "POST"
    }
  ]
}
```

### Get Workspace Triggers

**GET** `/api/workspaces/:workspace_id/triggers`

Get all active triggers for a workspace.

**Response:**
```json
{
  "success": true,
  "workspace_id": "workspace-123",
  "count": 2,
  "jobs": [...]
}
```

### Delete Workspace Triggers

**DELETE** `/api/workspaces/:workspace_id/triggers`

Remove all triggers for a workspace.

**Response:**
```json
{
  "success": true,
  "workspace_id": "workspace-123",
  "removed": 2
}
```

### Health Check

**GET** `/health`

Check if the API is running.

**Response:**
```json
{
  "status": "ok",
  "timestamp": "2025-11-16T01:22:00.000Z"
}
```

## Cron Expression Examples

- `0 */2 * * *` - Every 2 hours
- `0 9 * * 1-5` - 9 AM on weekdays
- `*/15 * * * *` - Every 15 minutes
- `0 0 * * 0` - Every Sunday at midnight
- `0 12 1 * *` - 12 PM on the first day of every month

## Trigger Configuration

Each trigger must include:

- `cron` (string, required): Cron expression for scheduling
- `url` (string, required): URL to send the HTTP request to
- `method` (string, required): HTTP method (GET, POST, PUT, PATCH, DELETE)
- `payload` (object, optional): Request body for POST/PUT/PATCH requests
- `headers` (object, optional): HTTP headers to include in the request

## How It Works

1. **API receives request** with workspace_id and triggers
2. **Remove existing jobs** for that workspace_id
3. **Create new repeatable jobs** in BullMQ with cron schedules
4. **Worker processes jobs** when they're triggered by the schedule
5. **Execute HTTP requests** based on trigger configuration

## Architecture

- **Express API**: Handles HTTP requests and manages triggers
- **BullMQ Queue**: Stores and schedules jobs with cron patterns
- **Worker**: Processes jobs and executes HTTP requests
- **Redis**: Backend for BullMQ (queue storage and pub/sub)

## Notes

- Jobs are automatically retried up to 3 times on failure
- Completed jobs are kept for 24 hours (last 100)
- Failed jobs are kept indefinitely (last 1000)
- Worker can process up to 10 jobs concurrently
- HTTP requests have a 30-second timeout
