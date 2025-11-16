import express from 'express';
import { WorkspaceService } from '../services/workspace.service.js';

const router = express.Router();
const workspaceService = new WorkspaceService();

/**
 * POST /api/workspaces/:workspace_id/triggers
 * Update triggers for a workspace
 */
router.post('/:workspace_id/triggers', async (req, res) => {
  try {
    const { workspace_id } = req.params;
    const { triggers } = req.body;

    if (!triggers) {
      return res.status(400).json({
        success: false,
        error: 'triggers array is required in request body',
      });
    }

    const result = await workspaceService.updateWorkspaceTriggers(workspace_id, triggers);

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
 * GET /api/workspaces/:workspace_id/triggers
 * Get all triggers for a workspace
 */
router.get('/:workspace_id/triggers', async (req, res) => {
  try {
    const { workspace_id } = req.params;

    const jobs = await workspaceService.getWorkspaceJobs(workspace_id);

    res.status(200).json({
      success: true,
      workspace_id,
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
 * DELETE /api/workspaces/:workspace_id/triggers
 * Remove all triggers for a workspace
 */
router.delete('/:workspace_id/triggers', async (req, res) => {
  try {
    const { workspace_id } = req.params;

    const removedCount = await workspaceService.removeWorkspaceJobs(workspace_id);

    res.status(200).json({
      success: true,
      workspace_id,
      removed: removedCount,
    });
  } catch (error) {
    console.error('Error removing workspace triggers:', error);

    res.status(500).json({
      success: false,
      error: error.message,
    });
  }
});

export default router;
