import { Redis } from 'ioredis';
import dotenv from 'dotenv';

dotenv.config();

/**
 * Create Redis connection from URL
 * @param {string} redisUrl - Redis connection URL
 * @returns {Redis} Redis connection instance
 */
export function createRedisConnection(redisUrl = process.env.REDIS_URL) {
  if (!redisUrl) {
    throw new Error('Redis URL is required');
  }

  const connection = new Redis(redisUrl, {
    maxRetriesPerRequest: null,
    enableReadyCheck: false,
  });

  connection.on('error', (err) => {
    console.error('Redis connection error:', err);
  });

  connection.on('connect', () => {
    console.log('Redis connected successfully');
  });

  return connection;
}

// Default connection for the application
export const redisConnection = createRedisConnection();
