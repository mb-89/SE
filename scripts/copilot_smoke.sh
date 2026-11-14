#!/usr/bin/env bash
# The smoke test of SE under a real GitHub Copilot (docs/copilot.md, "Smoke test"): the pinned
# Copilot CLI runs SE's agent once, non-interactively, from this checkout as a plugin, and
# scripts/copilot.py `smoke-verdict` passes its JSON lines where they hold SE's greeting and one
# answered call of an `se` tool.
#
#   copilot_smoke.sh [--record]
#
# It runs only where COPILOT_GITHUB_TOKEN is set, on Node 22 or later. One result line,
# `copilot smoke: passed|failed|skipped: <why>`; exit code 0 passed, 1 failed, 2 skipped.
# --record also writes the run's JSON lines to tests/fixtures/copilot/smoke.jsonl, the fixture the
# helper's test reads in place of the synthetic one.
set -u
version="1.0.112" # the Copilot CLI this smoke test is pinned to (npm @github/copilot)
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="${here%/*}"
record=""
[ "${1:-}" = "--record" ] && record=1
skip() { echo "copilot smoke: skipped: $*"; exit 2; }
[ -n "${COPILOT_GITHUB_TOKEN:-}" ] || skip "COPILOT_GITHUB_TOKEN is not set"
command -v node >/dev/null 2>&1 || skip "no Node on PATH (needs 22 or later)"
command -v npx >/dev/null 2>&1 || skip "no npx on PATH"
major="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null)"
[ "${major:-0}" -ge 22 ] 2>/dev/null || skip "Node ${major:-?} is older than 22"
out="$(mktemp)"
trap 'rm -f "$out" "$out.err"' EXIT
cd "$root" || exit 1
COPILOT_AUTO_UPDATE=false npx --yes "@github/copilot@$version" --plugin-dir=. --agent se -p status \
  --output-format json --allow-tool='se' --no-ask-user --trust-folder >"$out" 2>"$out.err"
code=$?
if [ -n "$record" ]; then
  mkdir -p "$root/tests/fixtures/copilot"
  cp "$out" "$root/tests/fixtures/copilot/smoke.jsonl"
  echo "recorded tests/fixtures/copilot/smoke.jsonl; run the public check before committing it"
fi
[ -s "$out.err" ] && sed 's/^/copilot: /' "$out.err" | tail -n 5 >&2
"$root/.githooks/se-script" copilot.py smoke-verdict "$out" --exit-code "$code"
