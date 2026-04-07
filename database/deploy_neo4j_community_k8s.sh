#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST_PATH="${SCRIPT_DIR}/neo4j.community.k8s.yaml"
NAMESPACE="z-graph"

if ! command -v kubectl >/dev/null 2>&1; then
  echo "kubectl not found. Please install kubectl first."
  exit 1
fi

echo "Applying Neo4j Community Kubernetes manifest..."
kubectl apply -f "${MANIFEST_PATH}"

echo "Waiting for deployment rollout..."
kubectl -n "${NAMESPACE}" rollout status deployment/neo4j-community --timeout=300s

echo
echo "Neo4j Community is deployed."
echo "Useful commands:"
echo "  kubectl -n ${NAMESPACE} get pods,svc,pvc"
echo "  kubectl -n ${NAMESPACE} logs deploy/neo4j-community"
echo "  kubectl -n ${NAMESPACE} port-forward svc/neo4j 7474:7474 7687:7687"
echo
echo "Then connect with:"
echo "  Browser: http://localhost:7474"
echo "  Bolt URI: bolt://localhost:7687"
echo "  Username/password: neo4j / password (change Secret before production)"
