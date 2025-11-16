import { triggerQueue } from '../queue/trigger.queue.js';

/**
 * Service for managing workspace triggers
 */
export class WorkspaceService {
  /**
   * Update triggers for a workspace
   * Removes all existing jobs and creates new ones based on the provided triggers
   * @param {string} workspace_id - Workspace identifier
   * @param {Array} triggers - Array of trigger configurations
   * @returns {Promise<Object>} Result of the operation
   */
  async updateWorkspaceTriggers(workspace_id, triggers) {
    if (!workspace_id) {
      throw new Error('workspace_id is required');
    }

    if (!Array.isArray(triggers)) {
      throw new Error('triggers must be an array');
    }

    // Validate triggers
    for (const trigger of triggers) {
      this.validateTrigger(trigger);
    }

    try {
      // Step 1: Remove all existing jobs for this workspace
      const removedCount = await this.removeWorkspaceJobs(workspace_id);

      console.log(`Removed ${removedCount} existing jobs for workspace ${workspace_id}`);

      // Step 2: Add new jobs
      const addedJobs = [];

      for (let i = 0; i < triggers.length; i++) {
        const trigger = triggers[i];
        const jobName = `${workspace_id}-trigger-${i}`;

        const job = await triggerQueue.add(
          jobName,
          {
            workspace_id,
            trigger,
          },
          {
            repeat: {
              pattern: trigger.cron,
            },
            jobId: `${workspace_id}:${i}`, // Unique job ID
          }
        );

        addedJobs.push({
          jobId: job.id,
          jobName: job.name,
          cron: trigger.cron,
          url: trigger.url,
          method: trigger.method,
        });
      }

      return {
        success: true,
        workspace_id,
        removed: removedCount,
        added: addedJobs.length,
        jobs: addedJobs,
      };
    } catch (error) {
      console.error('Error updating workspace triggers:', error);
      throw error;
    }
  }

  /**
   * Remove all jobs for a specific workspace
   * @param {string} workspace_id - Workspace identifier
   * @returns {Promise<number>} Number of jobs removed
   */
  async removeWorkspaceJobs(workspace_id) {
    try {
      // Get all repeatable jobs
      const repeatableJobs = await triggerQueue.getRepeatableJobs();

      let removedCount = 0;

      // Filter and remove jobs for this workspace
      for (const job of repeatableJobs) {
        // Check if job ID starts with workspace_id
        if (job.key && job.key.includes(workspace_id)) {
          await triggerQueue.removeRepeatableByKey(job.key);
          removedCount++;
        }
      }

      return removedCount;
    } catch (error) {
      console.error('Error removing workspace jobs:', error);
      throw error;
    }
  }

  /**
   * Validate trigger configuration
   * @param {Object} trigger - Trigger configuration
   */
  validateTrigger(trigger) {
    if (!trigger.cron) {
      throw new Error('Trigger must have a cron expression');
    }

    if (!trigger.url) {
      throw new Error('Trigger must have a URL');
    }

    if (!trigger.method) {
      throw new Error('Trigger must have an HTTP method');
    }

    const validMethods = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'];
    if (!validMethods.includes(trigger.method.toUpperCase())) {
      throw new Error(`Invalid HTTP method: ${trigger.method}. Must be one of: ${validMethods.join(', ')}`);
    }

    // Validate URL format
    try {
      new URL(trigger.url);
    } catch (error) {
      throw new Error(`Invalid URL: ${trigger.url}`);
    }
  }

  /**
   * Get all jobs for a workspace
   * @param {string} workspace_id - Workspace identifier
   * @returns {Promise<Array>} Array of jobs
   */
  async getWorkspaceJobs(workspace_id) {
    const repeatableJobs = await triggerQueue.getRepeatableJobs();

    return repeatableJobs.filter(job => job.key && job.key.includes(workspace_id));
  }
}
