# Metrics Queries with DuckDB

## Setup

```bash
pip install duckdb
```

## Python Example

```python
import duckdb

# Connect to DuckDB
con = duckdb.connect()

# Configure S3 credentials
con.execute("""
  CREATE SECRET s3_secret (
    TYPE S3,
    KEY_ID 'DO8017WFQWYG7EJNT3UT',
    SECRET 'nipYUkDRf48a5WK/OiQfPTTJuomBCRkjqVbrojnUg0c',
    ENDPOINT 'nyc3.digitaloceanspaces.com',
    REGION 'us-east-1'
  );
""")

# Query metrics from S3
query = """
SELECT *
FROM read_json_auto('s3://calvin-runtime-scheduler/metrics/**/*.json')
LIMIT 10;
"""

result = con.execute(query).fetchdf()
print(result)
```

## Example Queries

### 1. Success Rate by Workspace

```sql
SELECT
  workspace_id,
  COUNT(*) as total_executions,
  SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as successful,
  SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
  ROUND(100.0 * SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) / COUNT(*), 2) as success_rate
FROM read_json_auto('s3://calvin-runtime-scheduler/metrics/**/*.json')
GROUP BY workspace_id
ORDER BY total_executions DESC;
```

### 2. Average Execution Duration

```sql
SELECT
  workspace_id,
  AVG(duration_ms) as avg_duration_ms,
  MIN(duration_ms) as min_duration_ms,
  MAX(duration_ms) as max_duration_ms
FROM read_json_auto('s3://calvin-runtime-scheduler/metrics/**/*.json')
WHERE status = 'success'
GROUP BY workspace_id;
```

### 3. Executions by Hour

```sql
SELECT
  DATE_TRUNC('hour', CAST(timestamp AS TIMESTAMP)) as hour,
  COUNT(*) as execution_count,
  AVG(duration_ms) as avg_duration
FROM read_json_auto('s3://calvin-runtime-scheduler/metrics/**/*.json')
GROUP BY hour
ORDER BY hour DESC
LIMIT 24;
```

### 4. Failed Jobs with Error Messages

```sql
SELECT
  timestamp,
  workspace_id,
  trigger_url,
  trigger_method,
  error_message,
  retry_count,
  http_status
FROM read_json_auto('s3://calvin-runtime-scheduler/metrics/**/*.json')
WHERE status = 'failed'
ORDER BY timestamp DESC
LIMIT 100;
```

### 5. Top URLs by Execution Count

```sql
SELECT
  trigger_url,
  trigger_method,
  COUNT(*) as execution_count,
  AVG(duration_ms) as avg_duration_ms,
  SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success_count
FROM read_json_auto('s3://calvin-runtime-scheduler/metrics/**/*.json')
GROUP BY trigger_url, trigger_method
ORDER BY execution_count DESC
LIMIT 20;
```

### 6. Query Specific Date Range

```sql
SELECT *
FROM read_json_auto('s3://calvin-runtime-scheduler/metrics/year=2025/month=11/day=16/**/*.json')
WHERE CAST(timestamp AS TIMESTAMP) >= '2025-11-16 00:00:00'
  AND CAST(timestamp AS TIMESTAMP) < '2025-11-17 00:00:00';
```

### 7. Retry Analysis

```sql
SELECT
  retry_count,
  COUNT(*) as job_count,
  AVG(duration_ms) as avg_duration
FROM read_json_auto('s3://calvin-runtime-scheduler/metrics/**/*.json')
GROUP BY retry_count
ORDER BY retry_count;
```

## CLI Usage

```bash
# Interactive DuckDB shell
duckdb

# Run query from shell
D CREATE SECRET s3_secret (
    TYPE S3,
    KEY_ID 'DO8017WFQWYG7EJNT3UT',
    SECRET 'nipYUkDRf48a5WK/OiQfPTTJuomBCRkjqVbrojnUg0c',
    ENDPOINT 'nyc3.digitaloceanspaces.com',
    REGION 'us-east-1'
  );

D SELECT COUNT(*) FROM read_json_auto('s3://calvin-runtime-scheduler/metrics/**/*.json');
```

## Export Results

```python
# Export to CSV
con.execute("""
  COPY (
    SELECT * FROM read_json_auto('s3://calvin-runtime-scheduler/metrics/**/*.json')
  ) TO 'metrics_export.csv' (HEADER, DELIMITER ',');
""")

# Export to Parquet
con.execute("""
  COPY (
    SELECT * FROM read_json_auto('s3://calvin-runtime-scheduler/metrics/**/*.json')
  ) TO 'metrics_export.parquet' (FORMAT PARQUET);
""")
```

## Metrics Schema

```json
{
  "timestamp": "2025-11-16T14:10:45.840Z",
  "workspace_id": "metrics-test",
  "job_id": "repeat:abc123",
  "job_name": "metrics-test-trigger-0",
  "trigger_url": "https://httpbin.org/post",
  "trigger_method": "POST",
  "status": "success",  // or "failed"
  "duration_ms": 245,
  "http_status": 200,
  "error_message": null,
  "retry_count": 0
}
```

## Data Location

- **Bucket**: `calvin-runtime-scheduler`
- **Path Pattern**: `metrics/year={YYYY}/month={MM}/day={DD}/hour={HH}/metrics-{timestamp}.json`
- **Format**: JSON (one array per file)
- **Partitioning**: By year, month, day, and hour

## Notes

- Metrics are auto-flushed every 60 seconds or after 100 jobs
- Files are partitioned by date for efficient querying
- Use partition pruning by specifying year/month/day in paths
- DuckDB can read directly from S3 without downloading files
