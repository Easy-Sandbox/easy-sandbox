#!/bin/bash
cd /Users/anycodes/Documents/Qoder/2026-09-01/chat-1
echo "Starting hermes-agent build..."
.venv/bin/python -m easy_sandbox.cli.main --region cn-hangzhou template build-local examples/templates/hermes-agent --acr-namespace serverless-sandbox-test --acr-repo hermes-agent --tag e2e-20260922 --cpu 2 --memory 4096 --official-api
echo "Exit code: $?"
