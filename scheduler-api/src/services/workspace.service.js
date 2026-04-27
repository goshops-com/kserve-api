import { triggerQueue } from '../queue/trigger.queue.js';

/**
 * Service for managing workspace triggers
 */
export class WorkspaceService {
  static VALID_ENVS = ['dev', 'stg', 'prod'];

  /**
   * Build job prefix for a workspace + environment
   */
  jobPrefix(workspace_id, environment) {
    return `${workspace_id}-${environment}`;
  }

  /**
   * Validate environment value
   */
  validateEnvironment(environment) {
    if (!WorkspaceService.VALID_ENVS.includes(environment)) {
      throw new Error(`Invalid environment: ${environment}. Must be one of: ${WorkspaceService.VALID_ENVS.join(', ')}`);
    }
  }

  /**
   * Update triggers for a workspace
   */
  async updateWorkspaceTriggers(workspace_id, triggers, environment = 'dev') {
    if (!workspace_id) {
      throw new Error('workspace_id is required');
    }

    if (!Array.isArray(triggers)) {
      throw new Error('triggers must be an array');
    }

    this.validateEnvironment(environment);

    for (const trigger of triggers) {
      this.validateTrigger(trigger);
    }

    try {
      // Step 1: Remove existing jobs for this workspace + environment only
      const removedCount = await this.removeWorkspaceJobs(workspace_id, environment);

      console.log(`Removed ${removedCount} existing jobs for workspace ${workspace_id} env=${environment}`);

      // Step 2: Add new jobs
      const prefix = this.jobPrefix(workspace_id, environment);
      const addedJobs = [];

      for (let i = 0; i < triggers.length; i++) {
        const trigger = triggers[i];
        const jobName = `${prefix}-trigger-${i}`;

        const job = await triggerQueue.add(
          jobName,
          {
            workspace_id,
            environment,
            trigger,
          },
          {
            repeat: {
              pattern: trigger.cron,
            },
            jobId: `${workspace_id}:${environment}:${i}`,
            attempts: 3,
            backoff: {
              type: 'exponential',
              delay: 2000,
            },
            removeOnComplete: {
              age: 3600,
              count: 100,
            },
            removeOnFail: {
              age: 86400,
              count: 1000,
            },
          }
        );

        addedJobs.push({
          jobId: job.id,
          jobName: job.name,
          environment,
          cron: trigger.cron,
          url: trigger.url,
          method: trigger.method,
        });
      }

      return {
        success: true,
        workspace_id,
        environment,
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
   * Check if a job name matches a workspace + environment
   * Treats legacy jobs (without env) as 'dev'
   */
  jobMatches(jobName, workspace_id, environment) {
    if (!jobName) return false;

    const newPrefix = `${workspace_id}-${environment}-trigger-`;
    if (jobName.startsWith(newPrefix)) return true;

    // Legacy jobs (no env in name): "{workspace_id}-trigger-N" - treat as dev
    if (environment === 'dev') {
      const legacyPrefix = `${workspace_id}-trigger-`;
      if (jobName.startsWith(legacyPrefix)) return true;
    }

    return false;
  }

  /**
   * Remove jobs for a workspace.
   * If environment is null/undefined -> removes ALL jobs for that workspace (any env, incl. legacy)
   * If environment is set -> removes only jobs of that env (legacy jobs counted as dev)
   */
  async removeWorkspaceJobs(workspace_id, environment = null) {
    try {
      const repeatableJobs = await triggerQueue.getRepeatableJobs();

      let removedCount = 0;

      for (const job of repeatableJobs) {
        if (!job.name) continue;

        let shouldRemove = false;

        if (!environment) {
          // No env filter: remove every job containing this workspace_id
          shouldRemove = job.name.includes(workspace_id);
        } else {
          shouldRemove = this.jobMatches(job.name, workspace_id, environment);
        }

        if (shouldRemove) {
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

    try {
      new URL(trigger.url);
    } catch (error) {
      throw new Error(`Invalid URL: ${trigger.url}`);
    }
  }

  /**
   * Get jobs for a workspace, optionally filtered by environment
   */
  async getWorkspaceJobs(workspace_id, environment = null) {
    const repeatableJobs = await triggerQueue.getRepeatableJobs();

    if (environment) {
      const prefix = this.jobPrefix(workspace_id, environment);
      return repeatableJobs.filter(job => job.name && job.name.startsWith(prefix));
    }

    // No environment filter: return all jobs for this workspace
    return repeatableJobs.filter(job => job.name && job.name.includes(workspace_id));
  }
}
