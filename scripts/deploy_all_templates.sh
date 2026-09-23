#!/usr/bin/env bash
# Deploy all 10 templates one by one via CLI build-local
# Usage: bash scripts/deploy_all_templates.sh
set -euo pipefail

PYTHON=".venv/bin/python"
CLI="$PYTHON -m easy_sandbox.cli.main"
REGION="cn-hangzhou"
ACR_NS="serverless-sandbox-test"
TAG="e2e-20260922"

# Template name -> cpu memory
declare -A TEMPLATES
TEMPLATES=(
  ["python-hello"]="2 2048"
  ["node-web"]="1 2048"
  ["browser-automation"]="2 4096"
  ["claude-code"]="2 4096"
  ["codex"]="2 4096"
  ["deepseek-harness"]="2 4096"
  ["hermes-agent"]="2 4096"
  ["openclaw"]="2 4096"
  ["qoder"]="2 4096"
  ["qwen-code"]="2 4096"
)

ORDER=(python-hello node-web browser-automation claude-code codex deepseek-harness hermes-agent openclaw qoder qwen-code)

RESULTS_FILE="/tmp/deploy_results_$(date +%Y%m%d_%H%M%S).txt"
echo "Template | ExitCode | Status" > "$RESULTS_FILE"

for name in "${ORDER[@]}"; do
  read -r cpu mem <<< "${TEMPLATES[$name]}"
  echo ""
  echo "========================================="
  echo "Deploying: $name (cpu=$cpu, memory=$mem)"
  echo "========================================="
  
  START_TIME=$(date +%s)
  
  $CLI --region "$REGION" template build-local \
    "examples/templates/$name" \
    --acr-namespace "$ACR_NS" \
    --acr-repo "$name" \
    --tag "$TAG" \
    --cpu "$cpu" \
    --memory "$mem" \
    --official-api 2>&1 && EXIT_CODE=$? || EXIT_CODE=$?
  
  END_TIME=$(date +%s)
  ELAPSED=$((END_TIME - START_TIME))
  
  echo "$name | exit=$EXIT_CODE | elapsed=${ELAPSED}s" >> "$RESULTS_FILE"
  echo "--- $name completed in ${ELAPSED}s with exit code $EXIT_CODE ---"
done

echo ""
echo "========================================="
echo "DEPLOYMENT SUMMARY"
echo "========================================="
cat "$RESULTS_FILE"
