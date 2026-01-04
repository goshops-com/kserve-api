from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, Optional
from kubernetes import client, config
from kubernetes.client.rest import ApiException
import logging
import os
import requests
import time

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="CalvinCode Deployment API")

# Load Kubernetes config (in-cluster or local)
try:
    config.load_incluster_config()
    logger.info("Loaded in-cluster Kubernetes config")
except:
    config.load_kube_config()
    logger.info("Loaded local Kubernetes config")

# Create Kubernetes API client
api_client = client.ApiClient()
custom_api = client.CustomObjectsApi(api_client)
core_v1 = client.CoreV1Api(api_client)

# Constants
KNATIVE_GROUP = "serving.knative.dev"
KNATIVE_VERSION = "v1"
KNATIVE_SERVICE_PLURAL = "services"
DOMAIN_MAPPING_PLURAL = "domainmappings"
DOMAIN_MAPPING_VERSION = "v1beta1"
DEFAULT_NAMESPACE = os.getenv("DEFAULT_NAMESPACE", "default")
DOMAIN = os.getenv("DOMAIN", "calvinruntime.net")

# Cloudflare cache invalidation and analytics
CLOUDFLARE_ZONE_ID = os.getenv("CLOUDFLARE_ZONE_ID")
CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN")
CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID", "920b1a6e159cf77dab28969103a4765b")


class DeploymentRequest(BaseModel):
    name: str
    image: str  # format: registry/path:tag
    envs: Optional[Dict[str, str]] = {}
    namespace: Optional[str] = DEFAULT_NAMESPACE
    custom_domain: Optional[str] = None  # Optional custom domain (e.g., "myapp.example.com")


class DeploymentResponse(BaseModel):
    name: str
    namespace: str
    action: str  # "created" or "updated"
    status: str
    url: Optional[str] = None


def create_knative_service_spec(name: str, image: str, envs: Dict[str, str]) -> dict:
    """Create Knative Service spec for customer app deployment"""

    # Convert envs dict to list of env vars
    env_list = [{"name": k, "value": v} for k, v in envs.items()]

    # Auto-inject service URL for self-ping keep-alive pattern
    service_url = f"https://{name}.{DOMAIN}"
    env_list.append({"name": "SERVICE_URL", "value": service_url})

    return {
        "apiVersion": f"{KNATIVE_GROUP}/{KNATIVE_VERSION}",
        "kind": "Service",
        "metadata": {
            "name": name,
            "labels": {
                "app": name,
                "managed-by": "calvincode"
            }
        },
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {
                        "autoscaling.knative.dev/min-scale": "0",
                        "autoscaling.knative.dev/max-scale": "10",
                        "autoscaling.knative.dev/target": "100"
                    }
                },
                "spec": {
                    "containers": [{
                        "image": image,
                        "env": env_list,
                        "ports": [{
                            "containerPort": 8080,
                            "protocol": "TCP"
                        }],
                        "resources": {
                            "requests": {
                                "cpu": "100m",
                                "memory": "128Mi"
                            },
                            "limits": {
                                "cpu": "1",
                                "memory": "512Mi"
                            }
                        }
                    }]
                }
            }
        }
    }


def create_domain_mapping_spec(domain_name: str, service_name: str, namespace: str) -> dict:
    """Create DomainMapping spec for clean URL"""
    return {
        "apiVersion": f"{KNATIVE_GROUP}/{DOMAIN_MAPPING_VERSION}",
        "kind": "DomainMapping",
        "metadata": {
            "name": domain_name,
            "namespace": namespace
        },
        "spec": {
            "ref": {
                "name": service_name,
                "kind": "Service",
                "apiVersion": f"{KNATIVE_GROUP}/{KNATIVE_VERSION}"
            }
        }
    }


def get_knative_service(name: str, namespace: str):
    """Get Knative Service if it exists"""
    try:
        return custom_api.get_namespaced_custom_object(
            group=KNATIVE_GROUP,
            version=KNATIVE_VERSION,
            namespace=namespace,
            plural=KNATIVE_SERVICE_PLURAL,
            name=name
        )
    except ApiException as e:
        if e.status == 404:
            return None
        raise


def get_domain_mapping(domain_name: str, namespace: str):
    """Get DomainMapping if it exists"""
    try:
        return custom_api.get_namespaced_custom_object(
            group=KNATIVE_GROUP,
            version=DOMAIN_MAPPING_VERSION,
            namespace=namespace,
            plural=DOMAIN_MAPPING_PLURAL,
            name=domain_name
        )
    except ApiException as e:
        if e.status == 404:
            return None
        raise


def create_or_update_domain_mapping(domain_name: str, service_name: str, namespace: str):
    """Create or update DomainMapping for a domain"""
    try:
        existing = get_domain_mapping(domain_name, namespace)
        mapping_spec = create_domain_mapping_spec(domain_name, service_name, namespace)

        if existing is None:
            logger.info(f"Creating DomainMapping: {domain_name} -> {service_name}")
            custom_api.create_namespaced_custom_object(
                group=KNATIVE_GROUP,
                version=DOMAIN_MAPPING_VERSION,
                namespace=namespace,
                plural=DOMAIN_MAPPING_PLURAL,
                body=mapping_spec
            )
        else:
            logger.info(f"DomainMapping already exists: {domain_name}")

    except ApiException as e:
        logger.error(f"Failed to create DomainMapping: {e.status} - {e.reason}")
        # Don't fail the deployment if DomainMapping fails
    except Exception as e:
        logger.error(f"Unexpected error creating DomainMapping: {str(e)}")


def delete_domain_mapping(domain_name: str, namespace: str):
    """Delete DomainMapping for a specific domain"""
    try:
        existing = get_domain_mapping(domain_name, namespace)

        if existing is not None:
            logger.info(f"Deleting DomainMapping: {domain_name}")
            custom_api.delete_namespaced_custom_object(
                group=KNATIVE_GROUP,
                version=DOMAIN_MAPPING_VERSION,
                namespace=namespace,
                plural=DOMAIN_MAPPING_PLURAL,
                name=domain_name
            )
    except ApiException as e:
        logger.error(f"Failed to delete DomainMapping: {e.status} - {e.reason}")
    except Exception as e:
        logger.error(f"Unexpected error deleting DomainMapping: {str(e)}")


def purge_cloudflare_cache(domain: str):
    """Purge Cloudflare cache for a domain after deployment"""
    try:
        url = f"https://api.cloudflare.com/client/v4/zones/{CLOUDFLARE_ZONE_ID}/purge_cache"
        headers = {
            "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}",
            "Content-Type": "application/json"
        }
        # Use 'hosts' for hostname-based purging (not 'prefixes' which expects URL paths)
        data = {
            "hosts": [domain]
        }

        logger.info(f"Purging Cloudflare cache for {domain}")
        response = requests.post(url, json=data, headers=headers, timeout=10)

        if response.status_code == 200:
            logger.info(f"Successfully purged Cloudflare cache for {domain}")
        else:
            logger.warning(f"Cloudflare cache purge failed: {response.status_code} - {response.text}")

    except Exception as e:
        logger.error(f"Error purging Cloudflare cache: {str(e)}")
        # Don't fail the deployment if cache purge fails


def warm_up_service(service_url: str):
    """Make a warm-up request to trigger pod creation and image pull"""
    try:
        logger.info(f"Warming up service: {service_url}")
        response = requests.get(service_url, timeout=15)
        logger.info(f"Warm-up complete - Status: {response.status_code}, Pod is now running with new image")
    except requests.exceptions.Timeout:
        logger.warning(f"Warm-up request timed out (cold start may take longer than expected)")
    except Exception as e:
        logger.warning(f"Warm-up request failed: {str(e)}")
        # Don't fail the deployment if warm-up fails


@app.get("/")
async def root():
    return {
        "service": "CalvinCode Deployment API",
        "version": "2.0.0",
        "platform": "Knative Serving",
        "endpoints": {
            "health": "/health",
            "analytics": "/analytics (GET)",
            "web_analytics": "/web-analytics (GET)",
            "web_performance": "/web-performance (GET)",
            "deploy": "/deploy (POST)",
            "list": "/apps (GET)",
            "get": "/apps/{namespace}/{name} (GET)",
            "delete": "/apps/{namespace}/{name} (DELETE)",
            "logs": "/logs/{name} (GET)"
        }
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/analytics")
async def get_analytics(
    service_name: Optional[str] = None,
    hours: int = 24
):
    """
    Get Cloudflare analytics for Knative services

    Args:
        service_name: Optional specific service name (e.g., 'kserve-api')
        hours: Number of hours to query (default: 24)

    Returns:
        Analytics data with requests, bandwidth, status codes, latency
    """
    try:
        from datetime import datetime, timedelta

        # Calculate time range
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=hours)

        # Cloudflare GraphQL endpoint
        graphql_url = "https://api.cloudflare.com/client/v4/graphql"
        headers = {
            "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}",
            "Content-Type": "application/json"
        }

        # Build hostname filter
        if service_name:
            # If service_name is a full domain (has dots), use as-is
            # Otherwise append default domain
            if "." in service_name and not service_name.endswith(f".{DOMAIN}"):
                hostname = service_name
            else:
                hostname = f"{service_name}.{DOMAIN}" if "." not in service_name else service_name
            hostname_filter = f', clientRequestHTTPHost: "{hostname}"'
        else:
            hostname_filter = ""

        # GraphQL query for metrics
        query = """
        query GetMetrics($zoneTag: string, $startTime: Time!, $endTime: Time!) {
            viewer {
                zones(filter: { zoneTag: $zoneTag }) {
                    httpRequestsAdaptiveGroups(
                        filter: {
                            datetime_geq: $startTime,
                            datetime_lt: $endTime%s
                        },
                        limit: 1000,
                        orderBy: [datetimeHour_DESC]
                    ) {
                        count
                        dimensions {
                            datetimeHour
                            clientRequestHTTPHost
                            edgeResponseStatus
                        }
                    }
                }
            }
        }
        """ % hostname_filter

        variables = {
            "zoneTag": CLOUDFLARE_ZONE_ID,
            "startTime": start_time.isoformat() + "Z",
            "endTime": end_time.isoformat() + "Z"
        }

        # Make request to Cloudflare
        logger.info(f"Querying Cloudflare analytics: {start_time} to {end_time}")
        response = requests.post(
            graphql_url,
            headers=headers,
            json={"query": query, "variables": variables},
            timeout=30
        )
        response.raise_for_status()

        result = response.json()

        # Parse and format response
        if "errors" in result and result["errors"] is not None:
            raise HTTPException(
                status_code=500,
                detail=f"Cloudflare API error: {result['errors']}"
            )

        groups = result.get("data", {}).get("viewer", {}).get("zones", [{}])[0].get("httpRequestsAdaptiveGroups", [])

        # Transform to readable format
        metrics = []
        for group in groups:
            dims = group["dimensions"]
            count = group.get("count", 0)

            hostname = dims.get("clientRequestHTTPHost", "")
            # Extract service name from hostname
            if hostname.endswith(f".{DOMAIN}"):
                svc_name = hostname.replace(f".{DOMAIN}", "")
            else:
                svc_name = hostname

            metrics.append({
                "timestamp": dims["datetimeHour"],
                "service_name": svc_name,
                "hostname": hostname,
                "status_code": dims.get("edgeResponseStatus"),
                "requests": count
            })

        # Calculate summary stats
        total_requests = sum(m["requests"] for m in metrics)
        unique_services = len(set(m["service_name"] for m in metrics))

        return {
            "summary": {
                "total_requests": total_requests,
                "unique_services": unique_services,
                "unique_hostnames": len(set(m["hostname"] for m in metrics)),
                "time_range": {
                    "start": start_time.isoformat() + "Z",
                    "end": end_time.isoformat() + "Z",
                    "hours": hours
                }
            },
            "metrics": metrics,
            "count": len(metrics)
        }

    except requests.exceptions.RequestException as e:
        logger.error(f"Cloudflare API request error: {str(e)}")
        raise HTTPException(status_code=502, detail=f"Cloudflare API error: {str(e)}")
    except Exception as e:
        logger.error(f"Analytics error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error: {type(e).__name__}: {str(e)}")


@app.get("/web-analytics")
async def get_web_analytics(
    host: Optional[str] = None,
    hours: int = 24
):
    """
    Get Cloudflare Web Analytics (RUM) data - page views, visits, performance

    Args:
        host: Optional hostname filter (e.g., 'www.gopersonal.com')
        hours: Number of hours to query (default: 24)

    Returns:
        Web analytics data with page loads, visits by host and path
    """
    try:
        from datetime import datetime, timedelta

        # Calculate time range
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=hours)

        # Cloudflare GraphQL endpoint
        graphql_url = "https://api.cloudflare.com/client/v4/graphql"
        headers = {
            "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}",
            "Content-Type": "application/json"
        }

        # Build hostname filter for the GraphQL query
        if host:
            host_filter = f', requestHost: "{host}"'
        else:
            host_filter = ""

        # GraphQL query for Web Analytics (RUM) page loads
        query = """
        query PageLoads($accountTag: string, $startTime: Time!, $endTime: Time!) {
            viewer {
                accounts(filter: { accountTag: $accountTag }) {
                    rumPageloadEventsAdaptiveGroups(
                        filter: {
                            datetime_geq: $startTime,
                            datetime_lt: $endTime%s
                        },
                        limit: 1000,
                        orderBy: [datetimeHour_DESC]
                    ) {
                        count
                        dimensions {
                            datetimeHour
                            requestHost
                            requestPath
                        }
                        sum {
                            visits
                        }
                    }
                }
            }
        }
        """ % host_filter

        variables = {
            "accountTag": CLOUDFLARE_ACCOUNT_ID,
            "startTime": start_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "endTime": end_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        }

        # Make request to Cloudflare
        logger.info(f"Querying Cloudflare Web Analytics: {start_time} to {end_time}")
        response = requests.post(
            graphql_url,
            headers=headers,
            json={"query": query, "variables": variables},
            timeout=30
        )
        response.raise_for_status()

        result = response.json()

        # Parse and format response
        if "errors" in result and result["errors"] is not None:
            raise HTTPException(
                status_code=500,
                detail=f"Cloudflare API error: {result['errors']}"
            )

        groups = result.get("data", {}).get("viewer", {}).get("accounts", [{}])[0].get("rumPageloadEventsAdaptiveGroups", [])

        # Transform to readable format
        page_views = []
        for group in groups:
            dims = group["dimensions"]
            page_loads = group.get("count", 0)
            visits = group.get("sum", {}).get("visits", 0)

            page_views.append({
                "timestamp": dims["datetimeHour"],
                "host": dims.get("requestHost", ""),
                "path": dims.get("requestPath", ""),
                "page_loads": page_loads,
                "visits": visits
            })

        # Calculate summary stats
        total_page_loads = sum(pv["page_loads"] for pv in page_views)
        total_visits = sum(pv["visits"] for pv in page_views)
        unique_hosts = len(set(pv["host"] for pv in page_views if pv["host"]))
        unique_paths = len(set(f"{pv['host']}{pv['path']}" for pv in page_views))

        return {
            "summary": {
                "total_page_loads": total_page_loads,
                "total_visits": total_visits,
                "unique_hosts": unique_hosts,
                "unique_paths": unique_paths,
                "time_range": {
                    "start": start_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "end": end_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "hours": hours
                }
            },
            "page_views": page_views,
            "count": len(page_views)
        }

    except requests.exceptions.RequestException as e:
        logger.error(f"Cloudflare API request error: {str(e)}")
        raise HTTPException(status_code=502, detail=f"Cloudflare API error: {str(e)}")
    except Exception as e:
        logger.error(f"Web Analytics error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error: {type(e).__name__}: {str(e)}")


@app.get("/web-performance")
async def get_web_performance(
    host: Optional[str] = None,
    hours: int = 24
):
    """
    Get Cloudflare Web Performance metrics - Core Web Vitals, timing data

    Args:
        host: Optional hostname filter (e.g., 'www.gopersonal.com')
        hours: Number of hours to query (default: 24)

    Returns:
        Web performance data with Core Web Vitals (LCP, FID, CLS, TTFB) and timing metrics
    """
    try:
        from datetime import datetime, timedelta

        # Calculate time range
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=hours)

        # Cloudflare GraphQL endpoint
        graphql_url = "https://api.cloudflare.com/client/v4/graphql"
        headers = {
            "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}",
            "Content-Type": "application/json"
        }

        # Build hostname filter for the GraphQL query
        if host:
            host_filter = f', requestHost: "{host}"'
        else:
            host_filter = ""

        # GraphQL query for Web Performance metrics - combine timing and web vitals
        query = """
        query WebPerformance($accountTag: string, $startTime: Time!, $endTime: Time!) {
            viewer {
                accounts(filter: { accountTag: $accountTag }) {
                    performance: rumPerformanceEventsAdaptiveGroups(
                        filter: {
                            datetime_geq: $startTime,
                            datetime_lt: $endTime%s
                        },
                        limit: 1000,
                        orderBy: [datetimeHour_DESC]
                    ) {
                        count
                        dimensions {
                            datetimeHour
                            requestHost
                        }
                        quantiles {
                            pageLoadTimeP75
                            dnsTimeP75
                            connectionTimeP75
                            requestTimeP75
                            responseTimeP75
                            firstContentfulPaintP75
                        }
                    }
                    webVitals: rumWebVitalsEventsAdaptiveGroups(
                        filter: {
                            datetime_geq: $startTime,
                            datetime_lt: $endTime%s
                        },
                        limit: 1000,
                        orderBy: [datetimeHour_DESC]
                    ) {
                        count
                        dimensions {
                            datetimeHour
                            requestHost
                        }
                        quantiles {
                            largestContentfulPaintP75
                            firstInputDelayP75
                            cumulativeLayoutShiftP75
                            timeToFirstByteP75
                            firstContentfulPaintP75
                        }
                    }
                }
            }
        }
        """ % (host_filter, host_filter)

        variables = {
            "accountTag": CLOUDFLARE_ACCOUNT_ID,
            "startTime": start_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "endTime": end_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        }

        # Make request to Cloudflare
        logger.info(f"Querying Cloudflare Web Performance: {start_time} to {end_time}")
        response = requests.post(
            graphql_url,
            headers=headers,
            json={"query": query, "variables": variables},
            timeout=30
        )
        response.raise_for_status()

        result = response.json()

        # Parse and format response
        if "errors" in result and result["errors"] is not None:
            raise HTTPException(
                status_code=500,
                detail=f"Cloudflare API error: {result['errors']}"
            )

        account_data = result.get("data", {}).get("viewer", {}).get("accounts", [{}])[0]
        perf_groups = account_data.get("performance", [])
        vitals_groups = account_data.get("webVitals", [])

        # Merge performance timing and web vitals by timestamp and host
        combined_data = {}

        # Process performance timing metrics
        for group in perf_groups:
            dims = group["dimensions"]
            key = (dims["datetimeHour"], dims.get("requestHost", ""))
            quantiles = group.get("quantiles", {})

            combined_data[key] = {
                "timestamp": dims["datetimeHour"],
                "host": dims.get("requestHost", ""),
                "sample_count": group.get("count", 0),
                "timing_p75": {
                    "page_load_ms": round(quantiles.get("pageLoadTimeP75", 0) / 1000, 2),
                    "dns_ms": round(quantiles.get("dnsTimeP75", 0) / 1000, 2),
                    "connection_ms": round(quantiles.get("connectionTimeP75", 0) / 1000, 2),
                    "request_ms": round(quantiles.get("requestTimeP75", 0) / 1000, 2),
                    "response_ms": round(quantiles.get("responseTimeP75", 0) / 1000, 2),
                    "fcp_ms": round(quantiles.get("firstContentfulPaintP75", 0) / 1000, 2)
                },
                "web_vitals_p75": {}
            }

        # Add web vitals data
        for group in vitals_groups:
            dims = group["dimensions"]
            key = (dims["datetimeHour"], dims.get("requestHost", ""))
            quantiles = group.get("quantiles", {})

            # Convert from microseconds to milliseconds (divide by 1000)
            vitals = {
                "lcp_ms": round(quantiles.get("largestContentfulPaintP75", 0) / 1000, 2),
                "fid_ms": round(quantiles.get("firstInputDelayP75", 0) / 1000, 2) if quantiles.get("firstInputDelayP75", 0) > 0 else 0,
                "cls": round(quantiles.get("cumulativeLayoutShiftP75", 0), 4),
                "ttfb_ms": round(quantiles.get("timeToFirstByteP75", 0) / 1000, 2),
                "fcp_ms": round(quantiles.get("firstContentfulPaintP75", 0) / 1000, 2)
            }

            if key in combined_data:
                combined_data[key]["web_vitals_p75"] = vitals
            else:
                combined_data[key] = {
                    "timestamp": dims["datetimeHour"],
                    "host": dims.get("requestHost", ""),
                    "sample_count": group.get("count", 0),
                    "timing_p75": {},
                    "web_vitals_p75": vitals
                }

        performance_data = list(combined_data.values())

        # Calculate summary stats
        total_samples = sum(pd["sample_count"] for pd in performance_data)
        unique_hosts = len(set(pd["host"] for pd in performance_data if pd["host"]))

        # Calculate averages for Core Web Vitals
        lcp_vals = [pd["web_vitals_p75"].get("lcp_ms", 0) for pd in performance_data if pd.get("web_vitals_p75", {}).get("lcp_ms", 0) > 0]
        fid_vals = [pd["web_vitals_p75"].get("fid_ms", 0) for pd in performance_data if pd.get("web_vitals_p75", {}).get("fid_ms", 0) > 0]
        cls_vals = [pd["web_vitals_p75"].get("cls", 0) for pd in performance_data if pd.get("web_vitals_p75", {}).get("cls", 0) > 0]
        ttfb_vals = [pd["web_vitals_p75"].get("ttfb_ms", 0) for pd in performance_data if pd.get("web_vitals_p75", {}).get("ttfb_ms", 0) > 0]
        page_load_vals = [pd["timing_p75"].get("page_load_ms", 0) for pd in performance_data if pd.get("timing_p75", {}).get("page_load_ms", 0) > 0]

        return {
            "summary": {
                "total_samples": total_samples,
                "unique_hosts": unique_hosts,
                "avg_web_vitals_p75": {
                    "lcp_ms": round(sum(lcp_vals) / len(lcp_vals), 2) if lcp_vals else 0,
                    "fid_ms": round(sum(fid_vals) / len(fid_vals), 2) if fid_vals else 0,
                    "cls": round(sum(cls_vals) / len(cls_vals), 4) if cls_vals else 0,
                    "ttfb_ms": round(sum(ttfb_vals) / len(ttfb_vals), 2) if ttfb_vals else 0
                },
                "avg_timing_p75": {
                    "page_load_ms": round(sum(page_load_vals) / len(page_load_vals), 2) if page_load_vals else 0
                },
                "time_range": {
                    "start": start_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "end": end_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "hours": hours
                },
                "notes": {
                    "lcp": "Largest Contentful Paint - loading performance (good: <2.5s)",
                    "fid": "First Input Delay - interactivity (good: <100ms)",
                    "cls": "Cumulative Layout Shift - visual stability (good: <0.1)",
                    "ttfb": "Time to First Byte - server response (good: <800ms)",
                    "page_load": "Total page load time",
                    "p75": "75th percentile - 75% of users experience this or better"
                }
            },
            "performance_data": performance_data,
            "count": len(performance_data)
        }

    except requests.exceptions.RequestException as e:
        logger.error(f"Cloudflare API request error: {str(e)}")
        raise HTTPException(status_code=502, detail=f"Cloudflare API error: {str(e)}")
    except Exception as e:
        logger.error(f"Web Performance error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error: {type(e).__name__}: {str(e)}")


@app.post("/deploy", response_model=DeploymentResponse)
async def deploy_app(request: DeploymentRequest):
    """
    Deploy or update an app using Knative Serving.
    If the app doesn't exist, it will be created.
    If it exists, it will be updated (triggering a new revision).
    Automatically creates a DomainMapping for clean URLs.
    """
    try:
        namespace = request.namespace
        name = request.name

        logger.info(f"Processing deployment request for {name} in namespace {namespace}")

        # Check if Knative Service exists
        existing = get_knative_service(name, namespace)

        # Create the spec
        knative_service = create_knative_service_spec(
            name=name,
            image=request.image,
            envs=request.envs
        )

        if existing is None:
            # Create new Knative Service
            logger.info(f"Creating new Knative Service: {name}")
            result = custom_api.create_namespaced_custom_object(
                group=KNATIVE_GROUP,
                version=KNATIVE_VERSION,
                namespace=namespace,
                plural=KNATIVE_SERVICE_PLURAL,
                body=knative_service
            )
            action = "created"
        else:
            # Update existing Knative Service
            logger.info(f"Updating existing Knative Service: {name}")
            result = custom_api.patch_namespaced_custom_object(
                group=KNATIVE_GROUP,
                version=KNATIVE_VERSION,
                namespace=namespace,
                plural=KNATIVE_SERVICE_PLURAL,
                name=name,
                body=knative_service
            )
            action = "updated"

        # Construct primary URL (Knative auto-configures subdomain, no DomainMapping needed)
        subdomain = f"{name}.{DOMAIN}"
        clean_url = f"https://{subdomain}"

        # If custom domain is provided, create DomainMapping for it
        if request.custom_domain:
            logger.info(f"Creating DomainMapping for custom domain: {request.custom_domain}")
            create_or_update_domain_mapping(request.custom_domain, name, namespace)
            # Purge cache for custom domain
            purge_cloudflare_cache(request.custom_domain)

        # Purge Cloudflare cache for subdomain
        purge_cloudflare_cache(subdomain)

        # Wait for cache purge to propagate to Cloudflare edge locations
        # This prevents the warm-up request from re-caching stale content
        logger.info("Waiting 3 seconds for cache purge to propagate...")
        time.sleep(3)

        # Warm up the service to trigger pod creation and image pull (using primary URL)
        warm_up_service(clean_url)

        return DeploymentResponse(
            name=name,
            namespace=namespace,
            action=action,
            status="success",
            url=clean_url
        )

    except ApiException as e:
        logger.error(f"Kubernetes API error: {e.status} - {e.reason}")
        logger.error(f"Error body: {e.body}")
        raise HTTPException(status_code=e.status, detail=str(e.reason))
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/apps")
async def list_apps(namespace: str = DEFAULT_NAMESPACE):
    """List all Knative Services (apps) in a namespace"""
    try:
        result = custom_api.list_namespaced_custom_object(
            group=KNATIVE_GROUP,
            version=KNATIVE_VERSION,
            namespace=namespace,
            plural=KNATIVE_SERVICE_PLURAL
        )

        apps = []
        for item in result.get("items", []):
            name = item["metadata"]["name"]

            # Skip infrastructure services
            if name in ["kserve-api", "scheduler-api"]:
                continue

            # Check if service is ready
            conditions = item.get("status", {}).get("conditions", [])
            ready = any(c.get("type") == "Ready" and c.get("status") == "True" for c in conditions)

            apps.append({
                "name": name,
                "namespace": item["metadata"]["namespace"],
                "url": f"https://{name}.{DOMAIN}",
                "ready": ready,
                "image": item.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [{}])[0].get("image", "unknown")
            })

        return {"apps": apps, "count": len(apps)}

    except ApiException as e:
        raise HTTPException(status_code=e.status, detail=str(e.reason))


@app.get("/apps/{namespace}/{name}")
async def get_app(namespace: str, name: str):
    """Get details of a specific Knative Service (app)"""
    try:
        result = get_knative_service(name, namespace)

        if result is None:
            raise HTTPException(status_code=404, detail=f"App {name} not found in namespace {namespace}")

        containers = result.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
        image = containers[0].get("image", "unknown") if containers else "unknown"

        return {
            "name": result["metadata"]["name"],
            "namespace": result["metadata"]["namespace"],
            "image": image,
            "url": f"https://{name}.{DOMAIN}",
            "conditions": result.get("status", {}).get("conditions", [])
        }

    except ApiException as e:
        raise HTTPException(status_code=e.status, detail=str(e.reason))


@app.delete("/apps/{namespace}/{name}")
async def delete_app(namespace: str, name: str):
    """Delete a Knative Service (app) and its DomainMapping"""
    try:
        existing = get_knative_service(name, namespace)

        if existing is None:
            raise HTTPException(status_code=404, detail=f"App {name} not found in namespace {namespace}")

        # Note: Custom domain mappings need to be deleted manually if they exist
        # Subdomain is auto-managed by Knative, no DomainMapping to delete

        # Delete Knative Service
        custom_api.delete_namespaced_custom_object(
            group=KNATIVE_GROUP,
            version=KNATIVE_VERSION,
            namespace=namespace,
            plural=KNATIVE_SERVICE_PLURAL,
            name=name
        )

        return {
            "name": name,
            "namespace": namespace,
            "status": "deleted"
        }

    except ApiException as e:
        raise HTTPException(status_code=e.status, detail=str(e.reason))


@app.get("/logs/{name}")
async def get_logs(name: str, namespace: str = DEFAULT_NAMESPACE, tail_lines: int = 100):
    """
    Get the latest logs for an app.
    Returns the latest 100 lines (or specified tail_lines) from the app pod.
    """
    try:
        # Check if Knative Service exists
        existing = get_knative_service(name, namespace)
        if existing is None:
            raise HTTPException(status_code=404, detail=f"App {name} not found in namespace {namespace}")

        # Find pods for this Knative Service
        # Knative creates pods with labels: serving.knative.dev/service={name}
        label_selector = f"serving.knative.dev/service={name}"

        pods = core_v1.list_namespaced_pod(
            namespace=namespace,
            label_selector=label_selector
        )

        if not pods.items:
            return {
                "name": name,
                "namespace": namespace,
                "logs": "",
                "message": "No pods found for this app. The app may not be running yet or scaled to zero."
            }

        # Get the most recent pod (by creation time)
        latest_pod = max(pods.items, key=lambda p: p.metadata.creation_timestamp)
        pod_name = latest_pod.metadata.name

        # Check if pod is ready
        if latest_pod.status.phase not in ["Running", "Succeeded"]:
            try:
                logs = core_v1.read_namespaced_pod_log(
                    name=pod_name,
                    namespace=namespace,
                    tail_lines=tail_lines
                )
            except ApiException:
                return {
                    "name": name,
                    "namespace": namespace,
                    "pod_name": pod_name,
                    "pod_status": latest_pod.status.phase,
                    "logs": "",
                    "message": f"Pod is in {latest_pod.status.phase} state and logs are not available yet."
                }
        else:
            # Get logs from the user container
            logs = core_v1.read_namespaced_pod_log(
                name=pod_name,
                namespace=namespace,
                tail_lines=tail_lines
            )

        return {
            "name": name,
            "namespace": namespace,
            "pod_name": pod_name,
            "pod_status": latest_pod.status.phase,
            "tail_lines": tail_lines,
            "logs": logs
        }

    except ApiException as e:
        raise HTTPException(status_code=e.status, detail=str(e.reason))
    except Exception as e:
        logger.error(f"Unexpected error fetching logs: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
