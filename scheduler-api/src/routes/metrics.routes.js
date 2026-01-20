import express from 'express';
import { metricsQueryService } from '../services/metrics-query.service.js';
import { triggerQueue } from '../queue/trigger.queue.js';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { readFileSync } from 'fs';

const router = express.Router();
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

/**
 * GET /metrics - Serve the dashboard HTML
 */
router.get('/', (req, res) => {
  const htmlPath = join(__dirname, '../views/metrics-dashboard.html');
  res.sendFile(htmlPath);
});

/**
 * GET /api/metrics/:workspace_id - Get metrics for a workspace
 */
router.get('/api/:workspace_id', async (req, res) => {
  try {
    const { workspace_id } = req.params;
    const limit = parseInt(req.query.limit) || 100;

    const metrics = await metricsQueryService.getWorkspaceMetrics(workspace_id, limit);

    // Get next scheduled execution time
    let nextExecution = null;
    try {
      const delayed = await triggerQueue.getDelayed(0, 100);
      const workspaceJob = delayed.find(j => j.name && j.name.includes(workspace_id));
      if (workspaceJob) {
        // The next execution time is in opts.prevMillis (the scheduled timestamp)
        const nextTime = workspaceJob.opts?.prevMillis || (workspaceJob.timestamp + (workspaceJob.delay || 0));
        nextExecution = new Date(nextTime).toISOString();
      }
    } catch (e) {
      console.error('Error fetching next execution:', e.message);
    }

    res.status(200).json({
      ...metrics,
      next_execution: nextExecution,
    });
  } catch (error) {
    console.error('Error fetching workspace metrics:', error);

    res.status(500).json({
      success: false,
      error: error.message,
    });
  }
});

export default router;
