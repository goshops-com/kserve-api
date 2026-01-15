import express from 'express';
import workspaceRoutes from './routes/workspace.routes.js';
import metricsRoutes from './routes/metrics.routes.js';
import { serverAdapter } from './config/bullboard.js';
import { triggerQueue } from './queue/trigger.queue.js';

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
    res.json({
      count: repeatableJobs.length,
      jobs: repeatableJobs,
    });
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
