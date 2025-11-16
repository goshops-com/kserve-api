# Long-Running Tasks Guide

## Problem
Knative scales pods to zero after 90 seconds of inactivity. If your app has background tasks running, they'll be killed when the pod scales down.

## Solution: Self-Ping Keep-Alive Pattern

Your app automatically receives a `SERVICE_URL` environment variable with its public URL. Use this to ping yourself and prevent scale-to-zero while tasks are running.

---

## Node.js Example

```javascript
const express = require('express');
const fetch = require('node-fetch');

const app = express();
const SERVICE_URL = process.env.SERVICE_URL; // Auto-injected by platform

// Track active background tasks
let activeTasks = 0;
let keepAliveInterval = null;

// Start keep-alive pinging
function startKeepAlive() {
  if (!keepAliveInterval) {
    keepAliveInterval = setInterval(() => {
      if (activeTasks > 0) {
        // Ping self to prevent scale-to-zero
        fetch(`${SERVICE_URL}/health`).catch(() => {});
        console.log(`Keep-alive ping (${activeTasks} tasks active)`);
      } else {
        // No more tasks, allow scale-to-zero
        clearInterval(keepAliveInterval);
        keepAliveInterval = null;
        console.log('All tasks complete, allowing scale-to-zero');
      }
    }, 60000); // Ping every 60 seconds
  }
}

// Health check endpoint
app.get('/health', (req, res) => {
  res.json({ status: 'healthy', activeTasks });
});

// Long-running task endpoint
app.post('/process-video', async (req, res) => {
  const jobId = Date.now().toString();

  // Return immediately
  res.json({
    job_id: jobId,
    status: 'processing',
    message: 'Task started in background'
  });

  // Start background task
  activeTasks++;
  startKeepAlive();

  try {
    // Your long-running work here
    await processVideo(req.body.videoUrl);
    console.log(`Job ${jobId} completed`);
  } finally {
    activeTasks--;
  }
});

app.listen(8080, () => {
  console.log('Server running on port 8080');
  console.log(`SERVICE_URL: ${SERVICE_URL}`);
});
```

---

## Python Example

```python
import os
import asyncio
import threading
from fastapi import FastAPI
from httpx import AsyncClient

app = FastAPI()
SERVICE_URL = os.getenv("SERVICE_URL")  # Auto-injected by platform

# Track active background tasks
active_tasks = 0
keep_alive_task = None

async def keep_alive_pinger():
    """Ping self every 60s while tasks are active"""
    global active_tasks
    async with AsyncClient() as client:
        while active_tasks > 0:
            try:
                await client.get(f"{SERVICE_URL}/health")
                print(f"Keep-alive ping ({active_tasks} tasks active)")
            except:
                pass
            await asyncio.sleep(60)
    print("All tasks complete, allowing scale-to-zero")

@app.get("/health")
async def health():
    return {"status": "healthy", "activeTasks": active_tasks}

@app.post("/process-video")
async def process_video(video_url: str):
    global active_tasks, keep_alive_task

    job_id = str(int(asyncio.get_event_loop().time()))

    # Start background task
    active_tasks += 1

    # Start keep-alive if not running
    if keep_alive_task is None:
        keep_alive_task = asyncio.create_task(keep_alive_pinger())

    # Return immediately
    asyncio.create_task(process_in_background(video_url, job_id))

    return {
        "job_id": job_id,
        "status": "processing",
        "message": "Task started in background"
    }

async def process_in_background(video_url: str, job_id: str):
    global active_tasks
    try:
        # Your long-running work here
        await asyncio.sleep(300)  # Simulated 5-min processing
        print(f"Job {job_id} completed")
    finally:
        active_tasks -= 1
```

---

## How It Works

1. **Customer sends request** → Your app starts background task
2. **App returns immediately** → Customer gets 202 Accepted + job_id
3. **Background task runs** → App pings itself every 60 seconds
4. **Self-ping resets idle timer** → Pod stays alive
5. **Task completes** → Stop pinging, pod scales to zero after 90s

```
Timeline:
00:00 - Request arrives, task starts, activeTasks = 1
00:00 - Return 202 Accepted to client (HTTP request complete)
00:00 - Start self-pinging every 60s
01:00 - Ping → Idle timer resets
02:00 - Ping → Idle timer resets
05:00 - Task completes, activeTasks = 0
05:00 - Stop pinging
06:30 - 90 seconds of idle → Pod scales to zero ✅
```

---

## Alternative: Set Min-Scale to 1

If you prefer to keep the pod always running:

```json
POST /deploy
{
  "name": "my-app",
  "image": "...",
  "minScale": 1  // Coming soon: Never scales to zero
}
```

**Tradeoff:** Pod always running = costs money even when idle (~$10-20/month)

---

## Best Practices

1. **Track task count accurately** - Increment before starting, decrement in `finally` block
2. **Use try/finally** - Ensure task counter decrements even on errors
3. **Log keep-alive pings** - Help with debugging
4. **Set reasonable ping interval** - 60 seconds is safe (90s timeout - 30s buffer)
5. **Health check should be lightweight** - Just return status, don't do work

---

## When NOT to Use This

If tasks routinely take > 1 hour, consider:
- Deploying a separate worker service with min-scale: 1
- Using Kubernetes Jobs (for batch/one-off tasks)
- External queue workers

For most cases (tasks < 30 minutes), self-ping is the simplest solution.
