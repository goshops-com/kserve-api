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

app = FastAPI(title="KServe Model Management API")

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
KSERVE_GROUP = "serving.kserve.io"
KSERVE_VERSION = "v1beta1"
KSERVE_PLURAL = "inferenceservices"
KNATIVE_GROUP = "serving.knative.dev"
KNATIVE_VERSION = "v1beta1"
DOMAIN_MAPPING_PLURAL = "domainmappings"
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
    predictor_url: Optional[str] = None


def create_inference_service_spec(name: str, image: str, envs: Dict[str, str]) -> dict:
    """Create InferenceService spec"""

    # Convert envs dict to list of env vars
    env_list = [{"name": k, "value": v} for k, v in envs.items()]

    return {
        "apiVersion": f"{KSERVE_GROUP}/{KSERVE_VERSION}",
        "kind": "InferenceService",
        "metadata": {
            "name": name,
            "annotations": {
                "serving.kserve.io/enable-prometheus-scraping": "true",
                "autoscaling.knative.dev/initial-scale": "0",  # Start with 0 pods
                "autoscaling.knative.dev/min-scale": "0",  # Enable scale-to-zero
                "autoscaling.knative.dev/max-scale": "10"  # Max 10 pods
            }
        },
        "spec": {
            "predictor": {
                "containers": [{
                    "name": "kserve-container",
                    "image": image,
                    "imagePullPolicy": "Always",
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


def create_domain_mapping_spec(domain_name: str, service_name: str, namespace: str) -> dict:
    """Create DomainMapping spec for clean URL"""
    return {
        "apiVersion": f"{KNATIVE_GROUP}/{KNATIVE_VERSION}",
        "kind": "DomainMapping",
        "metadata": {
            "name": domain_name,
            "namespace": namespace
        },
        "spec": {
            "ref": {
                "name": service_name,
                "kind": "Service",
                "apiVersion": f"{KNATIVE_GROUP}/v1"
            }
        }
    }


def get_inference_service(name: str, namespace: str):
    """Get InferenceService if it exists"""
    try:
        return custom_api.get_namespaced_custom_object(
            group=KSERVE_GROUP,
            version=KSERVE_VERSION,
            namespace=namespace,
            plural=KSERVE_PLURAL,
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
            version=KNATIVE_VERSION,
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
        service_name = f"{name}-predictor"  # KServe creates this

        existing = get_domain_mapping(domain_name, namespace)
        mapping_spec = create_domain_mapping_spec(domain_name, service_name, namespace)

        if existing is None:
            logger.info(f"Creating DomainMapping: {domain_name} -> {service_name}")
            custom_api.create_namespaced_custom_object(
                group=KNATIVE_GROUP,
                version=KNATIVE_VERSION,
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
                version=KNATIVE_VERSION,
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
        "service": "KServe Model Management API",
        "version": "1.0.0",
        "endpoints": {
            "health": "/health",
            "deploy": "/deploy (POST)",
            "list": "/models (GET)",
            "get": "/models/{namespace}/{name} (GET)",
            "delete": "/models/{namespace}/{name} (DELETE)",
            "logs": "/logs/{name} (GET)"
        }
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}


def fix_podautoscaler_scale(name: str, namespace: str):
    """Fix PodAutoscaler min-scale annotation (KServe hardcodes it to 1)"""
    try:
        import time
        # Wait for PodAutoscaler to be created
        max_attempts = 30
        for attempt in range(max_attempts):
            try:
                # Get the latest revision name
                isvc = get_inference_service(name, namespace)
                if isvc and isvc.get("status", {}).get("components", {}).get("predictor", {}).get("latestCreatedRevision"):
                    revision_name = isvc["status"]["components"]["predictor"]["latestCreatedRevision"]

                    # Try to patch the PodAutoscaler
                    custom_api.patch_namespaced_custom_object(
                        group="autoscaling.internal.knative.dev",
                        version="v1alpha1",
                        namespace=namespace,
                        plural="podautoscalers",
                        name=revision_name,
                        body={
                            "metadata": {
                                "annotations": {
                                    "autoscaling.knative.dev/min-scale": "0"
                                }
                            }
                        }
                    )
                    logger.info(f"Fixed PodAutoscaler min-scale for {revision_name}")
                    return
            except ApiException as e:
                if e.status != 404:
                    logger.warning(f"Attempt {attempt + 1}: Error patching PodAutoscaler: {e.reason}")
            time.sleep(1)

        logger.warning(f"Failed to fix PodAutoscaler after {max_attempts} attempts")
    except Exception as e:
        logger.error(f"Unexpected error fixing PodAutoscaler: {str(e)}")


@app.post("/deploy", response_model=DeploymentResponse)
async def deploy_model(request: DeploymentRequest):
    """
    Deploy or update a model in KServe.
    If the model doesn't exist, it will be created.
    If it exists, it will be updated (triggering a restart).
    Automatically creates a DomainMapping for clean URLs.
    """
    try:
        namespace = request.namespace
        name = request.name

        logger.info(f"Processing deployment request for {name} in namespace {namespace}")

        # Check if InferenceService exists
        existing = get_inference_service(name, namespace)

        # Create the spec
        inference_service = create_inference_service_spec(
            name=name,
            image=request.image,
            envs=request.envs
        )

        if existing is None:
            # Create new InferenceService
            logger.info(f"Creating new InferenceService: {name}")
            result = custom_api.create_namespaced_custom_object(
                group=KSERVE_GROUP,
                version=KSERVE_VERSION,
                namespace=namespace,
                plural=KSERVE_PLURAL,
                body=inference_service
            )
            action = "created"
        else:
            # Update existing InferenceService
            logger.info(f"Updating existing InferenceService: {name}")
            result = custom_api.patch_namespaced_custom_object(
                group=KSERVE_GROUP,
                version=KSERVE_VERSION,
                namespace=namespace,
                plural=KSERVE_PLURAL,
                name=name,
                body=inference_service
            )
            action = "updated"

        # Create DomainMapping for clean URL
        create_or_update_domain_mapping(name, namespace)

        # Fix PodAutoscaler min-scale (KServe hardcodes it to 1)
        fix_podautoscaler_scale(name, namespace)

        # Construct URLs
        clean_url = f"https://{name}.{DOMAIN}"
        predictor_url = f"https://{name}-predictor.{DOMAIN}"

        return DeploymentResponse(
            name=name,
            namespace=namespace,
            action=action,
            status="success",
            url=clean_url,
            predictor_url=predictor_url
        )

    except ApiException as e:
        logger.error(f"Kubernetes API error: {e.status} - {e.reason}")
        raise HTTPException(status_code=e.status, detail=str(e.reason))
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/models")
async def list_models(namespace: str = DEFAULT_NAMESPACE):
    """List all InferenceServices in a namespace"""
    try:
        result = custom_api.list_namespaced_custom_object(
            group=KSERVE_GROUP,
            version=KSERVE_VERSION,
            namespace=namespace,
            plural=KSERVE_PLURAL
        )

        models = []
        for item in result.get("items", []):
            name = item["metadata"]["name"]
            models.append({
                "name": name,
                "namespace": item["metadata"]["namespace"],
                "url": f"https://{name}.{DOMAIN}",
                "predictor_url": f"https://{name}-predictor.{DOMAIN}",
                "ready": item.get("status", {}).get("conditions", [{}])[-1].get("status") == "True"
            })

        return {"models": models, "count": len(models)}

    except ApiException as e:
        raise HTTPException(status_code=e.status, detail=str(e.reason))


@app.get("/models/{namespace}/{name}")
async def get_model(namespace: str, name: str):
    """Get details of a specific InferenceService"""
    try:
        result = get_inference_service(name, namespace)

        if result is None:
            raise HTTPException(status_code=404, detail=f"Model {name} not found in namespace {namespace}")

        return {
            "name": result["metadata"]["name"],
            "namespace": result["metadata"]["namespace"],
            "image": result["spec"]["predictor"]["containers"][0]["image"],
            "url": f"https://{name}.{DOMAIN}",
            "predictor_url": f"https://{name}-predictor.{DOMAIN}",
            "conditions": result.get("status", {}).get("conditions", [])
        }

    except ApiException as e:
        raise HTTPException(status_code=e.status, detail=str(e.reason))


@app.delete("/models/{namespace}/{name}")
async def delete_model(namespace: str, name: str):
    """Delete an InferenceService and its DomainMapping"""
    try:
        existing = get_inference_service(name, namespace)

        if existing is None:
            raise HTTPException(status_code=404, detail=f"Model {name} not found in namespace {namespace}")

        # Delete DomainMapping first
        delete_domain_mapping(name, namespace)

        # Delete InferenceService
        custom_api.delete_namespaced_custom_object(
            group=KSERVE_GROUP,
            version=KSERVE_VERSION,
            namespace=namespace,
            plural=KSERVE_PLURAL,
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
    Get the latest logs for an app/model.
    Returns the latest 100 lines (or specified tail_lines) from the predictor pod.
    """
    try:
        # Check if InferenceService exists
        existing = get_inference_service(name, namespace)
        if existing is None:
            raise HTTPException(status_code=404, detail=f"Model {name} not found in namespace {namespace}")

        # Find pods for this InferenceService
        # KServe creates pods with labels: serving.kserve.io/inferenceservice={name}
        label_selector = f"serving.kserve.io/inferenceservice={name}"

        pods = core_v1.list_namespaced_pod(
            namespace=namespace,
            label_selector=label_selector
        )

        if not pods.items:
            return {
                "name": name,
                "namespace": namespace,
                "logs": "",
                "message": "No pods found for this model. The model may not be running yet."
            }

        # Get the most recent pod (by creation time)
        latest_pod = max(pods.items, key=lambda p: p.metadata.creation_timestamp)
        pod_name = latest_pod.metadata.name

        # Check if pod is ready
        if latest_pod.status.phase not in ["Running", "Succeeded"]:
            # Try to get logs anyway, but add a warning
            try:
                logs = core_v1.read_namespaced_pod_log(
                    name=pod_name,
                    namespace=namespace,
                    tail_lines=tail_lines,
                    container="kserve-container"
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
            # Get logs from the kserve-container
            try:
                logs = core_v1.read_namespaced_pod_log(
                    name=pod_name,
                    namespace=namespace,
                    tail_lines=tail_lines,
                    container="kserve-container"
                )
            except ApiException as e:
                if e.status == 400:
                    # Container might not exist or not ready, try without specifying container
                    logs = core_v1.read_namespaced_pod_log(
                        name=pod_name,
                        namespace=namespace,
                        tail_lines=tail_lines
                    )
                else:
                    raise

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
