#!/usr/bin/env bash
# Convenience wrapper; PowerShell users can use python -m evals.run directly.
set -euo pipefail
cd "$(dirname "$0")/.."
command="${1:-list}"
[ $# -gt 0 ] && shift
extras=(--group evals --extra openai)
for arg in "$@"; do
    [ "$arg" != "--trace" ] || extras+=(--extra otel)
done
case "$command" in
    list) exec uv run "${extras[@]}" python -m evals.run --list "$@" ;;
    check) exec uv run "${extras[@]}" python -m evals.run --check "$@" ;;
    prepare) exec uv run "${extras[@]}" python -m evals.environments prepare "$@" ;;
    report) exec uv run "${extras[@]}" python -m evals.report "$@" ;;
    evaluate) exec uv run "${extras[@]}" python -m evals.evaluate "$@" ;;
    all) exec uv run "${extras[@]}" python -m evals.run "$@" ;;
    *) exec uv run "${extras[@]}" python -m evals.run --tasks "$command" "$@" ;;
esac
