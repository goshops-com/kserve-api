import { S3Client, ListObjectsV2Command, GetObjectCommand } from '@aws-sdk/client-s3';

/**
 * Service for querying metrics from S3
 * Path structure: metrics/workspace={workspace_id}/year={year}/month={month}/day={day}/hour={hour}/
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
      const now = new Date();
      const allMetrics = [];

      // Search last 7 days - direct path to workspace metrics
      const BATCH_SIZE = 24; // Process 24 hours at a time

      for (let batchStart = 0; batchStart < 168 && allMetrics.length < limit; batchStart += BATCH_SIZE) {
        const batchPromises = [];

        for (let h = batchStart; h < Math.min(batchStart + BATCH_SIZE, 168); h++) {
          const date = new Date(now.getTime() - h * 60 * 60 * 1000);
          const year = date.getUTCFullYear();
          const month = String(date.getUTCMonth() + 1).padStart(2, '0');
          const day = String(date.getUTCDate()).padStart(2, '0');
          const hour = String(date.getUTCHours()).padStart(2, '0');

          // New path: workspace first, then time
          const newPrefix = `metrics/workspace=${workspaceId}/year=${year}/month=${month}/day=${day}/hour=${hour}/`;
          // Old path for backwards compatibility
          const oldPrefix = `metrics/year=${year}/month=${month}/day=${day}/hour=${hour}/`;

          batchPromises.push(this.fetchWorkspaceHourMetrics(newPrefix));
          batchPromises.push(this.fetchOldHourMetrics(oldPrefix, workspaceId));
        }

        const batchResults = await Promise.all(batchPromises);
        for (const metrics of batchResults) {
          allMetrics.push(...metrics);
        }
      }

      // Dedupe by timestamp + job_id
      const seen = new Set();
      const uniqueMetrics = allMetrics.filter(m => {
        const key = `${m.timestamp}-${m.job_id}`;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      });

      // Sort by timestamp descending and limit
      const sortedMetrics = uniqueMetrics
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
   * Fetch metrics from new workspace-partitioned path (no filtering needed)
   */
  async fetchWorkspaceHourMetrics(prefix) {
    const hourMetrics = [];
    try {
      const listCommand = new ListObjectsV2Command({
        Bucket: this.bucket,
        Prefix: prefix,
        MaxKeys: 50,
      });

      const listResult = await this.s3Client.send(listCommand);

      if (!listResult.Contents || listResult.Contents.length === 0) {
        return hourMetrics;
      }

      // Read all files in parallel - no filtering needed, all belong to this workspace
      const filePromises = listResult.Contents.map(async (file) => {
        try {
          const getCommand = new GetObjectCommand({
            Bucket: this.bucket,
            Key: file.Key,
          });
          const result = await this.s3Client.send(getCommand);
          const body = await result.Body.transformToString();
          return JSON.parse(body);
        } catch (e) {
          return [];
        }
      });

      const results = await Promise.all(filePromises);
      for (const metrics of results) {
        if (Array.isArray(metrics)) {
          hourMetrics.push(...metrics);
        } else {
          hourMetrics.push(metrics);
        }
      }
    } catch (e) {
      // Skip hours that can't be read
    }
    return hourMetrics;
  }

  /**
   * Fetch metrics from old path structure (requires filtering)
   */
  async fetchOldHourMetrics(prefix, workspaceId) {
    const hourMetrics = [];
    try {
      const listCommand = new ListObjectsV2Command({
        Bucket: this.bucket,
        Prefix: prefix,
        MaxKeys: 5, // Limit old path reads
      });

      const listResult = await this.s3Client.send(listCommand);

      if (!listResult.Contents || listResult.Contents.length === 0) {
        return hourMetrics;
      }

      const filePromises = listResult.Contents.map(async (file) => {
        try {
          const getCommand = new GetObjectCommand({
            Bucket: this.bucket,
            Key: file.Key,
          });
          const result = await this.s3Client.send(getCommand);
          const body = await result.Body.transformToString();
          const metrics = JSON.parse(body);
          return metrics.filter(m => m.workspace_id === workspaceId);
        } catch (e) {
          return [];
        }
      });

      const results = await Promise.all(filePromises);
      for (const metrics of results) {
        hourMetrics.push(...metrics);
      }
    } catch (e) {
      // Skip hours that can't be read
    }
    return hourMetrics;
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
        chart_data: [],
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
      .slice(-168); // Last 7 days of hourly data

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
