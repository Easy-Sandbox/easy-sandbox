#!/bin/bash
# Deploy remaining templates using stepped approach to avoid OOM
# Each step is a separate process
set -euo pipefail

WORKDIR="/Users/anycodes/Documents/Qoder/2026-09-01/chat-1"
PYTHON="$WORKDIR/.venv/bin/python"
TAG="e2e-20260922"
ACR_NS="serverless-sandbox-test"
ACR_REGISTRY="registry.cn-hangzhou.aliyuncs.com"
WHEEL="$WORKDIR/dist/easy_sandbox-0.1.0.dev0-py3-none-any.whl"
REGION="cn-hangzhou"

deploy_template() {
    local name="$1"
    local cpu="$2"
    local mem="$3"
    local alias="${4:-$name}"
    local tdir="$WORKDIR/examples/templates/$name"
    local acr_ref="$ACR_REGISTRY/$ACR_NS/$name:$TAG"

    echo ""
    echo "========================================="
    echo "Deploying: $name (alias=$alias, cpu=$cpu, memory=$mem)"
    echo "========================================="
    local start_ts=$(date +%s)

    # Step 1: Copy wheel
    cp "$WHEEL" "$tdir/"
    echo "[1/4] Wheel injected"

    # Step 2: Docker build
    echo "[2/4] Building Docker image..."
    docker build -t "$name:$TAG" --platform linux/amd64 "$tdir" 2>&1 | tail -5
    local build_exit=$?
    rm -f "$tdir/easy_sandbox-"*.whl
    if [ $build_exit -ne 0 ]; then
        echo "FAIL: Docker build failed for $name"
        echo "$name|FAIL|N/A|$acr_ref|docker-build-failed|$(($(date +%s)-start_ts))s" >> /tmp/deploy_results.txt
        return 1
    fi
    echo "[2/4] Build OK"

    # Step 3: Tag + Login + Push to ACR
    echo "[3/4] Pushing to ACR..."
    docker tag "$name:$TAG" "$acr_ref"
    # Login via project code
    $PYTHON -c "
from easy_sandbox.api.docker_builder import DockerBuilder
b = DockerBuilder()
from easy_sandbox.transport.config import load_config
cfg = load_config(region='$REGION')
creds = b.login_acr_with_aksk('$ACR_REGISTRY', cfg.access_key_id, cfg.access_key_secret, region='$REGION')
print('ACR login OK, temp user:', creds.get('tempUserName', 'N/A')[:8] + '...')
" 2>&1
    docker push "$acr_ref" 2>&1 | tail -5
    if [ $? -ne 0 ]; then
        echo "FAIL: ACR push failed for $name"
        echo "$name|FAIL|N/A|$acr_ref|acr-push-failed|$(($(date +%s)-start_ts))s" >> /tmp/deploy_results.txt
        return 1
    fi
    echo "[3/4] Push OK"

    # Step 4: Create/Update template via official API
    echo "[4/4] Creating/Updating template via official API..."
    $PYTHON -c "
from easy_sandbox.api.fc_template import create_official_template
from easy_sandbox.transport.config import load_config
from easy_sandbox.api.docker_builder import DockerBuilder

cfg = load_config(region='$REGION')
b = DockerBuilder()
creds = b.login_acr_with_aksk('$ACR_REGISTRY', cfg.access_key_id, cfg.access_key_secret, region='$REGION')

result = create_official_template(
    name='$alias',
    image='$acr_ref',
    access_key_id=cfg.access_key_id,
    access_key_secret=cfg.access_key_secret,
    region='$REGION',
    cpu=$cpu,
    memory_size=$mem,
    generation=1,
    envd_inject=True,
    registry_type='acr',
    registry_username=creds.get('tempUserName'),
    registry_password=creds.get('authorizationToken'),
)
print(f\"TemplateID={result.get('templateID')}\")
print(f\"StatusCode={result.get('statusCode')}\")
print(f\"Message={result.get('message')}\")
" 2>&1
    local api_exit=$?
    local end_ts=$(date +%s)
    local elapsed=$((end_ts - start_ts))

    if [ $api_exit -ne 0 ]; then
        echo "FAIL: API call failed for $name"
        echo "$name|FAIL|N/A|$acr_ref|api-call-failed|${elapsed}s" >> /tmp/deploy_results.txt
        return 1
    fi
    echo "--- $name completed in ${elapsed}s ---"
}

# Clear results
echo "Template|Result|TemplateID|ACR_Ref|Status|Time" > /tmp/deploy_results.txt

# Deploy remaining templates
deploy_template "hermes-agent" 2 4096
deploy_template "openclaw" 2 4096
deploy_template "qoder" 2 4096
deploy_template "qwen-code" 2 4096

echo ""
echo "========================================="
echo "BATCH RESULTS"
echo "========================================="
cat /tmp/deploy_results.txt
