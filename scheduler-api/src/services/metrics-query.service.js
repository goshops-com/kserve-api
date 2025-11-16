import { S3Client, ListObjectsV2Command, GetObjectCommand } from '@aws-sdk/client-s3';

/**
 * Service for querying metrics from S3
 */
export class MetricsQueryService {
  constructor() {
    this.s3Client = new S3Client({
      endpoint: process.env.S3_ENDPOINT,
      region: process.env.S3_REGION || 'us-east-1',
      credentials: {
        accessKeyId: process.env.S3_ACCESS_KEY,
        secretAccessKey: process.env.S3_SECRET_KEY,
      },
      forcePathStyle: true,
    });

    this.bucket = process.env.S3_BUCKET || 'scheduler-metrics';
  }

  /**
   * Get latest metrics for a workspace
   */
  async getWorkspaceMetrics(workspaceId, limit = 100) {
    try {
      // List recent metric files
      const now = new Date();
      const prefixes = [];

      // Check last 7 days
      for (let i = 0; i < 7; i++) {
        const date = new Date(now);
        date.setDate(date.getDate() - i);
        const year = date.getUTCFullYear();
        const month = String(date.getUTCMonth() + 1).padStart(2, '0');
        const day = String(date.getUTCDate()).padStart(2, '0');
        prefixes.push(`metrics/year=${year}/month=${month}/day=${day}/`);
      }

      const allMetrics = [];

      // Fetch metrics from each prefix
      for (const prefix of prefixes) {
        const listCommand = new ListObjectsV2Command({
          Bucket: this.bucket,
          Prefix: prefix,
          MaxKeys: 50,
        });

        const listResult = await this.s3Client.send(listCommand);

        if (!listResult.Contents || listResult.Contents.length === 0) {
          continue;
        }

        // Sort by last modified descending
        const files = listResult.Contents.sort((a, b) =>
          b.LastModified - a.LastModified
        ).slice(0, 10); // Get last 10 files per day

        // Fetch and parse each file
        for (const file of files) {
          const getCommand = new GetObjectCommand({
            Bucket: this.bucket,
            Key: file.Key,
          });

          const result = await this.s3Client.send(getCommand);
          const body = await result.Body.transformToString();
          const metrics = JSON.parse(body);

          // Filter by workspace_id
          const workspaceMetrics = metrics.filter(m => m.workspace_id === workspaceId);
          allMetrics.push(...workspaceMetrics);
        }

        // If we have enough metrics, stop searching
        if (allMetrics.length >= limit) {
          break;
        }
      }

      // Sort by timestamp descending and limit
      const sortedMetrics = allMetrics
        .sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))
        .slice(0, limit);

      // Calculate stats
      const stats = this.calculateStats(sortedMetrics);

      return {
        workspace_id: workspaceId,
        total: sortedMetrics.length,
        stats,
        executions: sortedMetrics,
      };
    } catch (error) {
      console.error('Error fetching metrics:', error);
      throw error;
    }
  }

  /**
   * Calculate statistics from metrics
   */
  calculateStats(metrics) {
    if (metrics.length === 0) {
      return {
        total: 0,
        success: 0,
        failed: 0,
        success_rate: 0,
        avg_duration: 0,
      };
    }

    const success = metrics.filter(m => m.status === 'success').length;
    const failed = metrics.filter(m => m.status === 'failed').length;
    const successRate = (success / metrics.length) * 100;
    const avgDuration = metrics.reduce((sum, m) => sum + m.duration_ms, 0) / metrics.length;

    // Group by hour for chart data
    const hourlyData = {};
    metrics.forEach(m => {
      const hour = new Date(m.timestamp).toISOString().substring(0, 13) + ':00:00';
      if (!hourlyData[hour]) {
        hourlyData[hour] = { success: 0, failed: 0 };
      }
      hourlyData[hour][m.status]++;
    });

    const chartData = Object.entries(hourlyData)
      .map(([hour, counts]) => ({
        hour,
        success: counts.success,
        failed: counts.failed,
      }))
      .sort((a, b) => a.hour.localeCompare(b.hour))
      .slice(-24); // Last 24 hours

    return {
      total: metrics.length,
      success,
      failed,
      success_rate: Math.round(successRate * 100) / 100,
      avg_duration: Math.round(avgDuration),
      chart_data: chartData,
    };
  }
}

export const metricsQueryService = new MetricsQueryService();
