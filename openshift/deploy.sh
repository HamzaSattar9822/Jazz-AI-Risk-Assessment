#!/usr/bin/env bash
# Build locally, push to the OpenShift internal registry, apply manifests in ai-risk.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NAMESPACE="${NAMESPACE:-ai-risk}"
APP_NAME="${APP_NAME:-jazz-ai-risk-assessment}"
TAG="${TAG:-latest}"
IMAGE_NAME="${IMAGE_NAME:-$APP_NAME}"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required tool: $1" >&2
    exit 1
  }
}

need docker
need oc
need openssl

if ! docker info >/dev/null 2>&1; then
  echo "Docker daemon is not running. Start Docker Desktop, then retry." >&2
  exit 1
fi

if ! oc whoami >/dev/null 2>&1; then
  echo "Not logged into OpenShift. Run:" >&2
  echo "  oc login --server=https://api.ocpv2.jazz.com.pk:6443" >&2
  echo "(use the token from the OpenShift web console → Copy login command)" >&2
  exit 1
fi

echo "==> Using project ${NAMESPACE}"
oc project "${NAMESPACE}" >/dev/null

echo "==> Ensuring ImageStream ${IMAGE_NAME}"
oc -n "${NAMESPACE}" get imagestream "${IMAGE_NAME}" >/dev/null 2>&1 || \
  oc -n "${NAMESPACE}" create imagestream "${IMAGE_NAME}"

echo "==> Logging Docker into the OpenShift image registry"
REG_HOST="$(oc registry info)"
# oc registry login writes podman auth; Docker needs an explicit login.
echo "$(oc whoami -t)" | docker login -u "$(oc whoami)" --password-stdin "${REG_HOST}"

FULL_IMAGE="${REG_HOST}/${NAMESPACE}/${IMAGE_NAME}:${TAG}"
INTERNAL_IMAGE="image-registry.openshift-image-registry.svc:5000/${NAMESPACE}/${IMAGE_NAME}:${TAG}"

echo "==> Building ${FULL_IMAGE} (linux/amd64 for cluster nodes)"
docker build --platform linux/amd64 -t "${FULL_IMAGE}" "${ROOT}"

echo "==> Pushing ${FULL_IMAGE}"
docker push "${FULL_IMAGE}"

echo "==> Ensuring JWT secret"
if ! oc -n "${NAMESPACE}" get secret aira-secrets >/dev/null 2>&1; then
  oc -n "${NAMESPACE}" create secret generic aira-secrets \
    --from-literal=JWT_SECRET="$(openssl rand -hex 32)"
else
  echo "    aira-secrets already exists (leaving JWT_SECRET unchanged)"
fi

echo "==> Applying PVC / Deployment / Service / Route"
oc apply -f "${ROOT}/openshift/01-pvc.yaml"
# Skip 02-secret.yaml if we already created the secret above
oc apply -f "${ROOT}/openshift/03-deployment.yaml"
oc apply -f "${ROOT}/openshift/04-service.yaml"
oc apply -f "${ROOT}/openshift/05-route.yaml"

echo "==> Pointing Deployment at pushed image"
oc -n "${NAMESPACE}" set image "deployment/${APP_NAME}" \
  "aira=${INTERNAL_IMAGE}"

# Patch CORS to the live Route host once it exists
ROUTE_HOST="$(oc -n "${NAMESPACE}" get route "${APP_NAME}" -o jsonpath='{.spec.host}' 2>/dev/null || true)"
if [[ -n "${ROUTE_HOST}" ]]; then
  echo "==> Setting CORS_ORIGINS=https://${ROUTE_HOST}"
  oc -n "${NAMESPACE}" set env "deployment/${APP_NAME}" \
    "CORS_ORIGINS=https://${ROUTE_HOST}"
fi

echo "==> Waiting for rollout"
oc -n "${NAMESPACE}" rollout status "deployment/${APP_NAME}" --timeout=180s

ROUTE_HOST="$(oc -n "${NAMESPACE}" get route "${APP_NAME}" -o jsonpath='{.spec.host}')"
echo
echo "Deployed."
echo "  URL:     https://${ROUTE_HOST}/"
echo "  Health:  https://${ROUTE_HOST}/health"
echo "  Image:   ${FULL_IMAGE}"
echo "  DB PVC:  aira-db  (sqlite at /data/aira.db)"
