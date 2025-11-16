import { Queue } from 'bullmq';
import { redisConnection } from '../config/redis.js';

/**
 * Queue for scheduled HTTP request triggers
 */
export const triggerQueue = new Queue('triggers', {
  connection: redisConnection,
  defaultJobOptions: {
    attempts: 3,
    backoff: {
      type: 'exponential',
      delay: 2000,
    },
    removeOnComplete: {
      count: 100, // Keep last 100 completed jobs
      age: 24 * 3600, // Keep for 24 hours
    },
    removeOnFail: {
      count: 1000, // Keep last 1000 failed jobs
    },
  },
});

triggerQueue.on('error', (err) => {
  console.error('Trigger queue error:', err);
});
