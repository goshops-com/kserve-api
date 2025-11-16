import { Worker } from 'bullmq';
import axios from 'axios';
import { createRedisConnection } from '../config/redis.js';

/**
 * Execute HTTP request based on trigger configuration
 * @param {Object} job - BullMQ job object
 */
async function executeTrigger(job) {
  const { workspace_id, trigger } = job.data;
  const { url, method, payload, headers } = trigger;

  console.log(`[${workspace_id}] Executing trigger: ${method} ${url}`);

  try {
    const response = await axios({
      method: method.toLowerCase(),
      url,
      data: payload,
      headers: headers || {},
      timeout: 30000, // 30 second timeout
    });

    console.log(`[${workspace_id}] Trigger executed successfully: ${response.status}`);

    return {
      success: true,
      status: response.status,
      data: response.data,
      executedAt: new Date().toISOString(),
    };
  } catch (error) {
    console.error(`[${workspace_id}] Trigger execution failed:`, error.message);

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
  await worker.close();
  process.exit(0);
});

process.on('SIGINT', async () => {
  console.log('SIGINT received, closing worker...');
  await worker.close();
  process.exit(0);
});
