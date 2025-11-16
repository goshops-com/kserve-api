import express from 'express';
import { metricsQueryService } from '../services/metrics-query.service.js';
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

    res.status(200).json(metrics);
  } catch (error) {
    console.error('Error fetching workspace metrics:', error);

    res.status(500).json({
      success: false,
      error: error.message,
    });
  }
});

export default router;
