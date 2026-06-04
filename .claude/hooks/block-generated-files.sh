#!/usr/bin/env bash
# PreToolUse hook (matcher: Edit|Write|MultiEdit).
# Blocks edits to auto-generated files per CLAUDE.md "What NOT to Do".
# Fail-safe: any unexpected condition -> exit 0 (no decision).

input=$(cat)
file_path=$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty' 2>/dev/null)
[ -z "$file_path" ] && exit 0

case "$file_path" in
  *frontend/src/client/*|*routeTree.gen.ts)
    reason="$file_path is auto-generated. Run 'bun run generate-client' (or ./scripts/generate-client.sh) instead of hand-editing it."
    jq -n --arg r "$reason" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}' 2>/dev/null
    exit 0
    ;;
esac
exit 0
