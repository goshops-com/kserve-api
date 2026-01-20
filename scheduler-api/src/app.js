import express from 'express';
import workspaceRoutes from './routes/workspace.routes.js';
import metricsRoutes from './routes/metrics.routes.js';
import { serverAdapter } from './config/bullboard.js';
import { triggerQueue } from './queue/trigger.queue.js';
import { S3Client, ListObjectsV2Command, GetObjectCommand } from '@aws-sdk/client-s3';

const app = express();

// Middleware
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// Request logging middleware
app.use((req, res, next) => {
  console.log(`${new Date().toISOString()} - ${req.method} ${req.path}`);
  next();
});

// Root endpoint (needed for Knative/Kourier probing)
app.get('/', (req, res) => {
  res.status(200).json({
    service: 'scheduler-api',
    status: 'ok',
  });
});

// Health check endpoint
app.get('/health', (req, res) => {
  res.status(200).json({
    status: 'ok',
    timestamp: new Date().toISOString(),
  });
});

// API routes
app.use('/api/workspaces', workspaceRoutes);

// Metrics dashboard
app.use('/metrics', metricsRoutes);

// Bull Board dashboard
app.use('/admin/queues', serverAdapter.getRouter());

// Debug endpoint to list all repeatable jobs
app.get('/debug/jobs', async (req, res) => {
  try {
    const repeatableJobs = await triggerQueue.getRepeatableJobs();
    const completed = await triggerQueue.getCompletedCount();
    const failed = await triggerQueue.getFailedCount();
    const delayed = await triggerQueue.getDelayedCount();
    const waiting = await triggerQueue.getWaitingCount();
    res.json({
      count: repeatableJobs.length,
      jobs: repeatableJobs,
      stats: { completed, failed, delayed, waiting }
    });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// Debug endpoint to get job data
app.get('/debug/job/:jobName', async (req, res) => {
  try {
    const { jobName } = req.params;
    const repeatableJobs = await triggerQueue.getRepeatableJobs();
    const job = repeatableJobs.find(j => j.name.includes(jobName));

    // Get recent completed jobs (last 200)
    const completed = await triggerQueue.getCompleted(0, 200);
    const matchingCompleted = completed.filter(j => j.name && j.name.includes(jobName));

    // Get recent failed jobs
    const failed = await triggerQueue.getFailed(0, 200);
    const matchingFailed = failed.filter(j => j.name && j.name.includes(jobName));

    // Get delayed jobs
    const delayed = await triggerQueue.getDelayed(0, 50);
    const matchingDelayed = delayed.filter(j => j.name && j.name.includes(jobName));

    res.json({
      repeatable: job || null,
      recentCompleted: matchingCompleted.map(j => ({
        id: j.id,
        name: j.name,
        data: j.data,
        finishedOn: j.finishedOn,
        processedOn: j.processedOn
      })),
      recentFailed: matchingFailed.map(j => ({
        id: j.id,
        name: j.name,
        data: j.data,
        failedReason: j.failedReason,
        finishedOn: j.finishedOn
      })),
      delayed: matchingDelayed.map(j => ({
        id: j.id,
        name: j.name,
        data: j.data,
        delay: j.delay,
        timestamp: j.timestamp
      }))
    });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// Debug endpoint to get all failed jobs
app.get('/debug/failed', async (req, res) => {
  try {
    const failed = await triggerQueue.getFailed(0, 100);
    res.json({
      count: failed.length,
      jobs: failed.map(j => ({
        id: j.id,
        name: j.name,
        data: j.data,
        failedReason: j.failedReason,
        attemptsMade: j.attemptsMade,
        finishedOn: j.finishedOn
      }))
    });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// Debug endpoint to check all delayed jobs
app.get('/debug/delayed', async (req, res) => {
  try {
    const delayed = await triggerQueue.getDelayed(0, 100);
    res.json({
      count: delayed.length,
      jobs: delayed.map(j => ({
        id: j.id,
        name: j.name,
        data: j.data,
        timestamp: j.timestamp,
        delay: j.delay,
        processedOn: j.processedOn,
        opts: j.opts
      }))
    });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// Debug endpoint to list S3 metrics files
app.get('/debug/s3-files', async (req, res) => {
  try {
    const s3Client = new S3Client({
      endpoint: process.env.S3_ENDPOINT,
      region: process.env.S3_REGION || 'us-east-1',
      credentials: {
        accessKeyId: process.env.S3_ACCESS_KEY,
        secretAccessKey: process.env.S3_SECRET_KEY,
      },
      forcePathStyle: true,
    });

    const bucket = process.env.S3_BUCKET;
    const prefix = req.query.prefix || 'metrics/year=';
    const listCommand = new ListObjectsV2Command({
      Bucket: bucket,
      Prefix: prefix,
      MaxKeys: 100,
    });

    const result = await s3Client.send(listCommand);
    res.json({
      bucket,
      prefix,
      count: result.Contents?.length || 0,
      files: result.Contents?.map(f => ({ key: f.Key, size: f.Size, lastModified: f.LastModified })) || []
    });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// Debug endpoint to read a specific S3 file
app.get('/debug/s3-read', async (req, res) => {
  try {
    const s3Client = new S3Client({
      endpoint: process.env.S3_ENDPOINT,
      region: process.env.S3_REGION || 'us-east-1',
      credentials: {
        accessKeyId: process.env.S3_ACCESS_KEY,
        secretAccessKey: process.env.S3_SECRET_KEY,
      },
      forcePathStyle: true,
    });

    const bucket = process.env.S3_BUCKET;
    const key = req.query.key;
    if (!key) return res.status(400).json({ error: 'key query param required' });

    const getCommand = new GetObjectCommand({ Bucket: bucket, Key: key });
    const result = await s3Client.send(getCommand);
    const body = await result.Body.transformToString();
    res.json(JSON.parse(body));
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// Debug endpoint to search metrics for a workspace
app.get('/debug/search-metrics/:workspaceId', async (req, res) => {
  try {
    const s3Client = new S3Client({
      endpoint: process.env.S3_ENDPOINT,
      region: process.env.S3_REGION || 'us-east-1',
      credentials: {
        accessKeyId: process.env.S3_ACCESS_KEY,
        secretAccessKey: process.env.S3_SECRET_KEY,
      },
      forcePathStyle: true,
    });

    const { workspaceId } = req.params;
    const bucket = process.env.S3_BUCKET;
    const found = [];

    // Search last 24 hours worth of files
    const now = new Date();
    for (let h = 0; h < 24; h++) {
      const date = new Date(now.getTime() - h * 60 * 60 * 1000);
      const year = date.getUTCFullYear();
      const month = String(date.getUTCMonth() + 1).padStart(2, '0');
      const day = String(date.getUTCDate()).padStart(2, '0');
      const hour = String(date.getUTCHours()).padStart(2, '0');
      const prefix = `metrics/year=${year}/month=${month}/day=${day}/hour=${hour}/`;

      const listCommand = new ListObjectsV2Command({ Bucket: bucket, Prefix: prefix, MaxKeys: 20 });
      const listResult = await s3Client.send(listCommand);

      if (!listResult.Contents) continue;

      // Sort by last modified descending
      const sortedFiles = listResult.Contents.sort((a, b) =>
        new Date(b.LastModified) - new Date(a.LastModified)
      ).slice(0, 10);

      for (const file of sortedFiles) {
        try {
          const getCommand = new GetObjectCommand({ Bucket: bucket, Key: file.Key });
          const result = await s3Client.send(getCommand);
          const body = await result.Body.transformToString();
          const metrics = JSON.parse(body);

          const matching = metrics.filter(m => m.workspace_id === workspaceId);
          if (matching.length > 0) {
            found.push(...matching);
          }
        } catch (e) { /* skip */ }
      }

      if (found.length >= 10) break;
    }

    res.json({ workspaceId, count: found.length, metrics: found });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// Debug endpoint to manually trigger a job
app.post('/debug/trigger-now/:workspaceId', async (req, res) => {
  try {
    const { workspaceId } = req.params;
    const repeatableJobs = await triggerQueue.getRepeatableJobs();
    const job = repeatableJobs.find(j => j.name.includes(workspaceId));

    if (!job) return res.status(404).json({ error: 'No job found for workspace' });

    // Get delayed job data
    const delayed = await triggerQueue.getDelayed(0, 50);
    const delayedJob = delayed.find(j => j.name.includes(workspaceId));

    if (!delayedJob) return res.status(404).json({ error: 'No delayed job found' });

    // Add immediate job with same data - use original job name format
    const newJob = await triggerQueue.add(
      delayedJob.name,  // Use same name as original
      delayedJob.data,
      { attempts: 3 }
    );

    res.json({ success: true, jobId: newJob.id, name: newJob.name, data: delayedJob.data });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// 404 handler
app.use((req, res) => {
  res.status(404).json({
    success: false,
    error: 'Route not found',
  });
});

// Error handler
app.use((err, req, res, next) => {
  console.error('Unhandled error:', err);

  res.status(500).json({
    success: false,
    error: err.message || 'Internal server error',
  });
});

export default app;
