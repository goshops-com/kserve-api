#!/usr/bin/env python3
"""
Knative Metrics Collector

Polls Kubernetes every minute to track running Knative services,
stores snapshots in S3, and reports usage to billing API.
"""

import os
import json
import logging
from datetime import datetime, timezone
from kubernetes import client, config
import boto3
from botocore.client import Config
import requests

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
S3_ENDPOINT = os.getenv("S3_ENDPOINT")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY")
S3_BUCKET = os.getenv("S3_BUCKET")
S3_REGION = os.getenv("S3_REGION", "us-east-1")
BILLING_API_URL = os.getenv("BILLING_API_URL", "https://calvincode-billing.go-shops.workers.dev/compute-usage")
NAMESPACE = os.getenv("NAMESPACE", "default")
POLLING_INTERVAL_SECONDS = 60

# Services to exclude from billing (infrastructure services)
EXCLUDED_SERVICES = {"kserve-api", "scheduler-api", "metrics-collector"}


def get_s3_client():
    """Create S3 client for DigitalOcean Spaces"""
    return boto3.client(
        's3',
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        region_name=S3_REGION,
        config=Config(signature_version='s3v4')
    )


def load_kubernetes_config():
    """Load Kubernetes configuration"""
    try:
        config.load_incluster_config()
        logger.info("Loaded in-cluster Kubernetes config")
    except:
        config.load_kube_config()
        logger.info("Loaded local Kubernetes config")


def get_running_services():
    """
    Get all running Knative service pods with their metadata.
    Returns dict: {service_name: {pods: count, env: {PROJECT_ID: ...}}}
    """
    v1 = client.CoreV1Api()

    # Get all pods with Knative service label
    pods = v1.list_namespaced_pod(
        namespace=NAMESPACE,
        label_selector="serving.knative.dev/service"
    )

    services = {}

    for pod in pods.items:
        # Only count running pods
        if pod.status.phase != "Running":
            continue

        labels = pod.metadata.labels or {}
        service_name = labels.get("serving.knative.dev/service")

        if not service_name:
            continue

        # Skip excluded services
        if service_name in EXCLUDED_SERVICES:
            continue

        # Extract env vars from container spec
        env_vars = {}
        if pod.spec.containers:
            for env in pod.spec.containers[0].env or []:
                if env.name == "PROJECT_ID" and env.value:
                    env_vars["PROJECT_ID"] = env.value
                elif env.name == "SERVICE_URL" and env.value:
                    env_vars["SERVICE_URL"] = env.value

        # Aggregate by service
        if service_name not in services:
            services[service_name] = {
                "pods": 0,
                "env": env_vars,
                "start_times": []
            }

        services[service_name]["pods"] += 1
        if pod.status.start_time:
            services[service_name]["start_times"].append(
                pod.status.start_time.isoformat()
            )

    return services


def save_snapshot_to_s3(s3_client, snapshot):
    """Save snapshot to S3"""
    try:
        timestamp = snapshot["timestamp"]
        date_str = timestamp[:10]  # YYYY-MM-DD

        # Save to daily folder
        key = f"metrics/snapshots/{date_str}/{timestamp}.json"

        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=key,
            Body=json.dumps(snapshot, indent=2),
            ContentType="application/json"
        )

        logger.info(f"Saved snapshot to s3://{S3_BUCKET}/{key}")
        return True
    except Exception as e:
        logger.error(f"Failed to save snapshot to S3: {e}")
        return False


def send_to_billing_api(subdomain: str, workspace: str, instances: int, seconds: int):
    """Send usage data to billing API"""
    try:
        payload = {
            "subdomain": subdomain,
            "workspace": workspace,
            "instances": instances,
            "seconds": seconds
        }

        response = requests.post(
            BILLING_API_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10
        )

        if response.status_code == 200:
            logger.info(f"Billing API success: {subdomain} - {instances} instances, {seconds}s")
            return True
        else:
            logger.warning(f"Billing API returned {response.status_code}: {response.text}")
            return False
    except Exception as e:
        logger.error(f"Failed to send to billing API: {e}")
        return False


def collect_and_report():
    """Main collection and reporting function"""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    logger.info(f"Starting metrics collection at {timestamp}")

    # Get running services
    services = get_running_services()

    if not services:
        logger.info("No running services found (excluding infrastructure)")
        return

    logger.info(f"Found {len(services)} running services")

    # Build snapshot
    snapshot = {
        "timestamp": timestamp,
        "services": {}
    }

    # Initialize S3 client
    s3_client = None
    if S3_ENDPOINT and S3_ACCESS_KEY:
        s3_client = get_s3_client()

    # Process each service
    for service_name, data in services.items():
        pods = data["pods"]
        seconds = pods * POLLING_INTERVAL_SECONDS  # Each pod contributes 60 seconds
        project_id = data["env"].get("PROJECT_ID")

        # Add to snapshot
        snapshot["services"][service_name] = {
            "pods": pods,
            "seconds": seconds,
            "project_id": project_id
        }

        logger.info(f"  {service_name}: {pods} pods, {seconds}s, PROJECT_ID={project_id or 'N/A'}")

        # Send to billing API if PROJECT_ID exists
        if project_id:
            send_to_billing_api(
                subdomain=service_name,
                workspace=project_id,
                instances=pods,
                seconds=seconds
            )
        else:
            logger.info(f"  Skipping billing for {service_name} - no PROJECT_ID")

    # Save snapshot to S3
    if s3_client:
        save_snapshot_to_s3(s3_client, snapshot)
    else:
        logger.warning("S3 not configured, skipping snapshot save")

    logger.info("Metrics collection complete")


def main():
    """Main entry point"""
    logger.info("Knative Metrics Collector starting...")

    # Load Kubernetes config
    load_kubernetes_config()

    # Run collection once (CronJob will handle scheduling)
    collect_and_report()

    logger.info("Metrics Collector finished")


if __name__ == "__main__":
    main()
