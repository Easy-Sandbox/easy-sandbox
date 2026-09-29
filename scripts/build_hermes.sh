#!/bin/bash
# Deploy the hermes-agent template from the SSOT catalog repo
# (Easy-Sandbox/awesome-templates); this repo keeps only the python-hello fixture.
cd /Users/anycodes/Documents/Qoder/2026-09-01/chat-1
echo "Fetching hermes-agent from Easy-Sandbox/awesome-templates..."
.venv/bin/python -m easy_sandbox.cli.main --region cn-hangzhou \
    template install hermes-agent --download-only
echo "Starting hermes-agent build..."
.venv/bin/python -m easy_sandbox.cli.main --region cn-hangzhou \
    template deploy "$HOME/.ebx/templates/Easy-Sandbox/awesome-templates/default/hermes-agent" \
    --acr-namespace serverless-sandbox-test --acr-repo hermes-agent \
    --tag e2e-20260922 --cpu 2 --memory 4096 --official-api
echo "Exit code: $?"
