import { Worker } from 'bullmq';
import axios from 'axios';
import { createRedisConnection } from '../config/redis.js';
import { metricsService } from '../services/metrics.service.js';

/**
 * Execute HTTP request based on trigger configuration
 * @param {Object} job - BullMQ job object
 */
async function executeTrigger(job) {
  const { workspace_id, trigger } = job.data;
  const { url, method, payload, headers } = trigger;
  const startTime = Date.now();

  console.log(`[${workspace_id}] Executing trigger: ${method} ${url}`);

  try {
    const response = await axios({
      method: method.toLowerCase(),
      url,
      data: payload,
      headers: headers || {},
      timeout: 30000, // 30 second timeout
    });

    const duration = Date.now() - startTime;

    console.log(`[${workspace_id}] Trigger executed successfully: ${response.status}`);

    // Log metrics
    await metricsService.logJobExecution({
      workspace_id,
      job_id: job.id,
      job_name: job.name,
      trigger_url: url,
      trigger_method: method,
      status: 'success',
      duration_ms: duration,
      http_status: response.status,
      retry_count: job.attemptsMade,
    });

    return {
      success: true,
      status: response.status,
      data: response.data,
      executedAt: new Date().toISOString(),
    };
  } catch (error) {
    const duration = Date.now() - startTime;

    console.error(`[${workspace_id}] Trigger execution failed:`, error.message);

    // Log metrics for failure
    await metricsService.logJobExecution({
      workspace_id,
      job_id: job.id,
      job_name: job.name,
      trigger_url: url,
      trigger_method: method,
      status: 'failed',
      duration_ms: duration,
      http_status: error.response?.status || null,
      error_message: error.message,
      retry_count: job.attemptsMade,
    });

    throw new Error(`Failed to execute trigger: ${error.message}`);
  }
}

/**
 * Create and start the trigger worker
 */
const connection = createRedisConnection();

const worker = new Worker('triggers', executeTrigger, {
  connection,
  concurrency: 10, // Process up to 10 jobs concurrently
  limiter: {
    max: 100, // Max 100 jobs
    duration: 1000, // per second
  },
});

worker.on('completed', (job) => {
  console.log(`Job ${job.id} completed successfully`);
});

worker.on('failed', (job, err) => {
  console.error(`Job ${job.id} failed:`, err.message);
});

worker.on('error', (err) => {
  console.error('Worker error:', err);
});

console.log('Trigger worker started and listening for jobs...');

// Graceful shutdown
process.on('SIGTERM', async () => {
  console.log('SIGTERM received, closing worker...');
  await metricsService.shutdown();
  await worker.close();
  process.exit(0);
});

process.on('SIGINT', async () => {
  console.log('SIGINT received, closing worker...');
  await metricsService.shutdown();
  await worker.close();
  process.exit(0);
});
