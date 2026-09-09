#!/usr/bin/env bash
# check-secrets.sh — scan staged files for hardcoded secrets.
# Compatible with POSIX-ish bash; called from the pre-commit hook
# (core.hooksPath) AND from the pre-commit framework (local hook).

echo "🔍 Checking staged files for sensitive information..."

# Collect staged files (added/modified) that still exist on disk.
STAGED_FILES=$(git diff --cached --name-only --diff-filter=ACM 2>/dev/null || true)

if [ -z "$STAGED_FILES" ]; then
    echo "✅ No staged files to check."
    exit 0
fi

FOUND=0

# Helper: grep staged files for a pattern, print matches, set FOUND=1.
check_pattern() {
    local label="$1"
    local pattern="$2"
    local flags="${3:-}"
    while IFS= read -r f; do
        [ -z "$f" ] && continue
        [ -f "$f" ] || continue
        # shellcheck disable=SC2086
        matches=$(grep -n $flags -E "$pattern" "$f" 2>/dev/null | grep -v 'example\|placeholder\|REPLACE_ME\|test\|mock\|fake\|your\|xxxx\|dummy\|sample\|some-\|startswith\|cached' || true)
        if [ -n "$matches" ]; then
            echo "❌ $label"
            echo "$matches" | while IFS= read -r line; do
                echo "   $f:$line"
            done
            FOUND=1
        fi
    done <<< "$STAGED_FILES"
}

# --- Existing patterns ---

# E2B API keys
check_pattern "Found hardcoded E2B API key!" 'e2b_[a-f0-9]{20,}'

# Alibaba Cloud AccessKey
check_pattern "Found hardcoded Alibaba Cloud AccessKey!" 'LTAI[a-zA-Z0-9]{12,}'

# GitHub personal access tokens
check_pattern "Found hardcoded GitHub token!" 'ghp_[a-zA-Z0-9]{36,}'

# --- New patterns ---

# OpenAI / LLM tokens (sk-...)
check_pattern "Found hardcoded OpenAI/LLM token!" 'sk-[a-zA-Z0-9]{20,}'

# AWS IAM access keys (AKIA...)
check_pattern "Found hardcoded AWS IAM key!" 'AKIA[0-9A-Z]{16}'

# Generic hardcoded secret assignments (case-insensitive)
check_pattern "Found hardcoded secret assignment!" '(api[_-]?key|secret|token|password)\s*=\s*["'"'"'][^"'"'"']{8,}' "-i"

if [ "$FOUND" -ne 0 ]; then
    echo ""
    echo "⛔ Commit blocked — remove hardcoded secrets before committing."
    exit 1
fi

echo "✅ No sensitive information found."
exit 0
