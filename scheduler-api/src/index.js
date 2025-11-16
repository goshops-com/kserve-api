import app from './app.js';
import { config } from './config/app.js';
import { redisConnection } from './config/redis.js';

const PORT = config.port;

// Start server
const server = app.listen(PORT, () => {
  console.log(`
🚀 Scheduler API Server Started
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Port:        ${PORT}
  Environment: ${config.nodeEnv}
  Redis:       ${config.redisUrl}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

API Endpoints:
  POST   /api/workspaces/:workspace_id/triggers
  GET    /api/workspaces/:workspace_id/triggers
  DELETE /api/workspaces/:workspace_id/triggers
  GET    /health

Dashboard:
  GET    /admin/queues - BullMQ Dashboard
  `);
});

// Graceful shutdown
process.on('SIGTERM', async () => {
  console.log('SIGTERM received, shutting down gracefully...');

  server.close(() => {
    console.log('HTTP server closed');
  });

  await redisConnection.quit();
  console.log('Redis connection closed');

  process.exit(0);
});

process.on('SIGINT', async () => {
  console.log('SIGINT received, shutting down gracefully...');

  server.close(() => {
    console.log('HTTP server closed');
  });

  await redisConnection.quit();
  console.log('Redis connection closed');

  process.exit(0);
});
