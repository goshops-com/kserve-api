import express from 'express';
import { WorkspaceService } from '../services/workspace.service.js';

const router = express.Router();
const workspaceService = new WorkspaceService();

/**
 * POST /api/workspaces/:workspace_id/triggers
 * Body: { triggers: [...], environment: "dev"|"stg"|"prod" }
 */
router.post('/:workspace_id/triggers', async (req, res) => {
  try {
    const { workspace_id } = req.params;
    const { triggers, environment = 'dev' } = req.body;

    if (!triggers) {
      return res.status(400).json({
        success: false,
        error: 'triggers array is required in request body',
      });
    }

    const result = await workspaceService.updateWorkspaceTriggers(workspace_id, triggers, environment);

    res.status(200).json(result);
  } catch (error) {
    console.error('Error updating workspace triggers:', error);

    res.status(400).json({
      success: false,
      error: error.message,
    });
  }
});

/**
 * GET /api/workspaces/:workspace_id/triggers?environment=dev
 */
router.get('/:workspace_id/triggers', async (req, res) => {
  try {
    const { workspace_id } = req.params;
    const { environment } = req.query;

    const jobs = await workspaceService.getWorkspaceJobs(workspace_id, environment || null);

    res.status(200).json({
      success: true,
      workspace_id,
      environment: environment || 'all',
      count: jobs.length,
      jobs,
    });
  } catch (error) {
    console.error('Error getting workspace triggers:', error);

    res.status(500).json({
      success: false,
      error: error.message,
    });
  }
});

/**
 * DELETE /api/workspaces/:workspace_id/triggers/by-key?key=...
 * Remove a single scheduled job by its BullMQ key
 */
router.delete('/:workspace_id/triggers/by-key', async (req, res) => {
  try {
    const { workspace_id } = req.params;
    const { key } = req.query;

    if (!key) {
      return res.status(400).json({ success: false, error: 'key query param required' });
    }

    if (!key.includes(workspace_id)) {
      return res.status(403).json({ success: false, error: 'Job key does not belong to this workspace' });
    }

    const result = await workspaceService.removeJobByKey(key);
    res.status(200).json({ success: true, workspace_id, ...result });
  } catch (error) {
    console.error('Error removing job by key:', error);
    res.status(400).json({ success: false, error: error.message });
  }
});

/**
 * DELETE /api/workspaces/:workspace_id/triggers
 *   - no query param  -> removes ALL jobs for the workspace (any env, including legacy)
 *   - ?environment=dev -> removes only that env (legacy jobs count as dev)
 */
router.delete('/:workspace_id/triggers', async (req, res) => {
  try {
    const { workspace_id } = req.params;
    const { environment } = req.query;

    if (environment) {
      workspaceService.validateEnvironment(environment);
    }

    const removedCount = await workspaceService.removeWorkspaceJobs(workspace_id, environment || null);

    res.status(200).json({
      success: true,
      workspace_id,
      environment: environment || 'all',
      removed: removedCount,
    });
  } catch (error) {
    console.error('Error removing workspace triggers:', error);

    res.status(400).json({
      success: false,
      error: error.message,
    });
  }
});

export default router;
