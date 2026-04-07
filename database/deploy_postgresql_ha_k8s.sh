#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="z-graph"
RELEASE_NAME="postgresql-ha"
CHART_REF="bitnami/postgresql-ha"

DB_USER="z_graph"
DB_PASSWORD="z_graph"
DB_NAME="z_graph"

if ! command -v kubectl >/dev/null 2>&1; then
  echo "kubectl not found. Please install kubectl first."
  exit 1
fi

if ! command -v helm >/dev/null 2>&1; then
  echo "helm not found. Please install Helm 3 first."
  exit 1
fi

echo "Ensuring Helm Bitnami repo is available..."
helm repo add bitnami https://charts.bitnami.com/bitnami >/dev/null 2>&1 || true
helm repo update >/dev/null

echo "Ensuring namespace exists: ${NAMESPACE}"
kubectl get namespace "${NAMESPACE}" >/dev/null 2>&1 || kubectl create namespace "${NAMESPACE}"

echo "Deploying ${CHART_REF} as release ${RELEASE_NAME}..."
helm upgrade --install "${RELEASE_NAME}" "${CHART_REF}" \
  --namespace "${NAMESPACE}" \
  --set postgresql.username="${DB_USER}" \
  --set postgresql.password="${DB_PASSWORD}" \
  --set postgresql.database="${DB_NAME}" \
  --wait \
  --timeout 10m

echo
echo "PostgreSQL HA deployed."
echo "Useful commands:"
echo "  helm list -n ${NAMESPACE}"
echo "  kubectl -n ${NAMESPACE} get pods,svc,statefulset,deploy"
echo "  kubectl -n ${NAMESPACE} get secret ${RELEASE_NAME}-postgresql"
echo
echo "Connection host (Pgpool service):"
echo "  ${RELEASE_NAME}-pgpool.${NAMESPACE}.svc.cluster.local"
echo
echo "Example connection string:"
echo "  postgresql://${DB_USER}:${DB_PASSWORD}@${RELEASE_NAME}-pgpool.${NAMESPACE}.svc.cluster.local:5432/${DB_NAME}"
