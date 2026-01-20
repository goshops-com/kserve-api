import { S3Client, PutObjectCommand } from '@aws-sdk/client-s3';
import parquet from 'parquetjs';
import { Buffer } from 'buffer';

/**
 * Metrics service for writing job execution data to S3 in Parquet format
 */
export class MetricsService {
  constructor() {
    this.s3Client = new S3Client({
      endpoint: process.env.S3_ENDPOINT,
      region: process.env.S3_REGION || 'us-east-1',
      credentials: {
        accessKeyId: process.env.S3_ACCESS_KEY,
        secretAccessKey: process.env.S3_SECRET_KEY,
      },
      forcePathStyle: true, // Required for DigitalOcean Spaces
    });

    this.bucket = process.env.S3_BUCKET || 'scheduler-metrics';
    this.metricsBuffer = [];
    this.bufferSize = parseInt(process.env.METRICS_BUFFER_SIZE) || 10;
    this.flushInterval = parseInt(process.env.METRICS_FLUSH_INTERVAL) || 60000; // 1 minute

    // Auto-flush timer
    this.startAutoFlush();
  }

  /**
   * Log a job execution result
   */
  async logJobExecution(data) {
    console.log(`📝 Logging metric for workspace: ${data.workspace_id}, job: ${data.job_name}`);

    const metric = {
      timestamp: new Date().toISOString(),
      workspace_id: data.workspace_id,
      job_id: data.job_id,
      job_name: data.job_name,
      trigger_url: data.trigger_url,
      trigger_method: data.trigger_method,
      status: data.status, // 'success' or 'failed'
      duration_ms: data.duration_ms,
      http_status: data.http_status,
      error_message: data.error_message || null,
      retry_count: data.retry_count || 0,
    };

    this.metricsBuffer.push(metric);
    console.log(`📝 Buffer size now: ${this.metricsBuffer.length}, workspaces in buffer: ${[...new Set(this.metricsBuffer.map(m => m.workspace_id))].join(', ')}`);

    // Flush if buffer is full
    if (this.metricsBuffer.length >= this.bufferSize) {
      await this.flush();
    }
  }

  /**
   * Flush metrics buffer to S3
   */
  async flush() {
    if (this.metricsBuffer.length === 0) {
      return;
    }

    const metricsToWrite = [...this.metricsBuffer];
    this.metricsBuffer = [];

    try {
      await this.writeToS3(metricsToWrite);
      console.log(`✅ Flushed ${metricsToWrite.length} metrics to S3`);
    } catch (error) {
      console.error('❌ Error flushing metrics to S3:', error.message);
      // Put metrics back in buffer for retry
      this.metricsBuffer.unshift(...metricsToWrite);
    }
  }

  /**
   * Write metrics to S3, partitioned by workspace
   */
  async writeToS3(metrics) {
    const now = new Date();
    const year = now.getUTCFullYear();
    const month = String(now.getUTCMonth() + 1).padStart(2, '0');
    const day = String(now.getUTCDate()).padStart(2, '0');
    const hour = String(now.getUTCHours()).padStart(2, '0');
    const timestamp = now.getTime();

    // Group metrics by workspace_id
    const byWorkspace = {};
    for (const metric of metrics) {
      const ws = metric.workspace_id;
      if (!byWorkspace[ws]) {
        byWorkspace[ws] = [];
      }
      byWorkspace[ws].push(metric);
    }

    // Write a file per workspace
    const writePromises = Object.entries(byWorkspace).map(async ([workspaceId, wsMetrics]) => {
      // S3 key partitioned by workspace first, then time
      const key = `metrics/workspace=${workspaceId}/year=${year}/month=${month}/day=${day}/hour=${hour}/metrics-${timestamp}.json`;

      const jsonData = JSON.stringify(wsMetrics, null, 2);
      const buffer = Buffer.from(jsonData, 'utf-8');

      const command = new PutObjectCommand({
        Bucket: this.bucket,
        Key: key,
        Body: buffer,
        ContentType: 'application/json',
        Metadata: {
          'record-count': String(wsMetrics.length),
          'workspace-id': workspaceId,
          'created-at': now.toISOString(),
        },
      });

      await this.s3Client.send(command);
      console.log(`📊 Wrote ${wsMetrics.length} metrics for ${workspaceId} to s3://${this.bucket}/${key}`);
    });

    await Promise.all(writePromises);
  }

  /**
   * Start auto-flush timer
   */
  startAutoFlush() {
    setInterval(() => {
      this.flush().catch(err => {
        console.error('Auto-flush error:', err.message);
      });
    }, this.flushInterval);

    console.log(`📊 Metrics auto-flush every ${this.flushInterval / 1000}s`);
  }

  /**
   * Graceful shutdown - flush remaining metrics
   */
  async shutdown() {
    console.log('Flushing remaining metrics before shutdown...');
    await this.flush();
  }
}

// Singleton instance
export const metricsService = new MetricsService();
