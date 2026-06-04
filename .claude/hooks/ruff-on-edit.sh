#!/usr/bin/env bash
# PostToolUse hook (matcher: Edit|Write|MultiEdit).
# Auto-fixes backend Python with ruff, mirroring .pre-commit-config.yaml.
# Non-blocking: always exit 0. mypy intentionally excluded (latency).

input=$(cat)
file_path=$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty' 2>/dev/null)
[ -z "$file_path" ] && exit 0

case "$file_path" in
  *backend/app/alembic/*) exit 0 ;;        # matches ruff [tool.ruff] exclude
  *backend/*.py)
    cd "${CLAUDE_PROJECT_DIR:-.}/backend" 2>/dev/null || exit 0
    uv run ruff check --fix --force-exclude "$file_path" 2>&1 || true
    ;;
esac
exit 0
