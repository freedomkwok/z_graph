#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST_PATH="${SCRIPT_DIR}/zep-graph.app.yaml"
NAMESPACE="z-graph"

if ! command -v kubectl >/dev/null 2>&1; then
  echo "kubectl not found. Please install kubectl first."
  exit 1
fi

echo "Applying app manifest..."
kubectl apply -f "${MANIFEST_PATH}"

echo "Waiting for app rollout..."
kubectl -n "${NAMESPACE}" rollout status deployment/zep-graph-app --timeout=300s

echo
echo "Deployment completed."
echo "Edit these placeholders before production use:"
echo "  - image: your-registry/zep-graph:prod"
echo "  - ingress host: zep-graph.example.com"
echo "  - secret values in zep-graph-secrets"
echo "  - PROJECT_STORAGE_CONNECTION_STRING if your postgres service name/host differs"
echo
echo "Useful commands:"
echo "  kubectl -n ${NAMESPACE} get pods,svc,ingress"
echo "  kubectl -n ${NAMESPACE} logs deploy/zep-graph-app"
