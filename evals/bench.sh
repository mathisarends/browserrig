#!/usr/bin/env bash
# Run the live-site benchmark by stage. See evals/README.md.
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: evals/bench.sh <command> [options for evals.run]

Commands
  practice    Demo sites with fixed content: tools, logins, files, widgets (~12 tasks)
  reference   Docs, papers, specs and data portals: multi-step research (~11 tasks)
  wild        Popular sites that change daily: realism check (~13 tasks)
  smoke       Five quick practice tasks, one per core capability
  all         Every stage
  list        List tasks with their stage and tags
  report      Summarise a results file: report <file> [--against <older file>]
  <names>     Task names, @stage or @tag, comma-separated, e.g. @upload,owid_csv

Options (passed on to evals.run)
  --repeat N      Run each task N times to see flakiness
  --parallel N    Concurrent browsers (default 3)
  --headed        Show the browser windows
  --humanlike     Keep human-like input pacing and the on-page cursor
  --provider NAME openai-codex (default, subscription) or openai (API key)
  --model NAME    Model (default: gpt-6.1-terra; openai also reads $OPENAI_MODEL)
  --trace         Export traces to Phoenix (start it first: docker compose up -d --wait)
  --label TEXT    Suffix for the results file (default: the command)

Examples
  evals/bench.sh smoke
  evals/bench.sh practice --repeat 2
  evals/bench.sh saucedemo_checkout --headed
  evals/bench.sh reference --trace
EOF
}

cd "$(dirname "$0")/.."

command="${1:-}"
[ $# -gt 0 ] && shift

case "$command" in
    "" | -h | --help | help)
        usage
        exit 0
        ;;
    list)
        exec uv run --extra openai python -m evals.run --list
        ;;
    report)
        exec uv run python -m evals.report "$@"
        ;;
    practice | reference | wild) selection="@$command" ;;
    all) selection="@practice,@reference,@wild" ;;
    smoke) selection="saucedemo_checkout,heroku_file_roundtrip,heroku_dialogs,w3c_widgets,todomvc_state" ;;
    *) selection="$command" ;;
esac

extras=(--extra openai)
label="${command//[^A-Za-z0-9_-]/_}"
for arg in "$@"; do
    case "$arg" in
        --trace) extras+=(--extra otel) ;;
        --label) label="" ;;
    esac
done

env_file=()
[ -f .env ] && env_file=(--env-file .env)

label_args=()
[ -n "$label" ] && label_args=(--label "$label")

exec uv run "${env_file[@]}" "${extras[@]}" python -m evals.run \
    --tasks "$selection" "${label_args[@]}" "$@"
