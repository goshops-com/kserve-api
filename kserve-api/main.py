from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, Optional
from kubernetes import client, config
from kubernetes.client.rest import ApiException
import logging
import os

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


class DeploymentRequest(BaseModel):
    name: str
    image: str  # format: registry/path:tag
    envs: Optional[Dict[str, str]] = {}
    namespace: Optional[str] = DEFAULT_NAMESPACE


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


def create_or_update_domain_mapping(name: str, namespace: str):
    """Create or update DomainMapping for clean URL"""
    try:
        domain_name = f"{name}.{DOMAIN}"
        service_name = name  # Direct Knative Service name (no -predictor suffix)

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


def delete_domain_mapping(name: str, namespace: str):
    """Delete DomainMapping"""
    try:
        domain_name = f"{name}.{DOMAIN}"
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


@app.get("/")
async def root():
    return {
        "service": "CalvinCode Deployment API",
        "version": "2.0.0",
        "platform": "Knative Serving",
        "endpoints": {
            "health": "/health",
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

        # Create DomainMapping for clean URL
        create_or_update_domain_mapping(name, namespace)

        # Construct URL
        clean_url = f"https://{name}.{DOMAIN}"

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

        # Delete DomainMapping first
        delete_domain_mapping(name, namespace)

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
