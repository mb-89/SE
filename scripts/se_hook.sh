#!/usr/bin/env bash
# SE's hook for one session event: posts the host's hook JSON on stdin to kern, the core SE pins, as
# `kern hook <event>`, and prints kern's answer as the hook's output.
#
#   se_hook.sh <event>     run by the Claude Code plugin's hooks (scripts/se_plugin.py)
#
# The binary is the one bootstrap.sh named for the project at the session's start, in
# <project>/.se/.runtime/kern.path. It fails open: where that names no binary on this machine yet or
# no core answers, it prints nothing and exits 0. Builtins only up to the one exec, so a hook costs
# kern's own start; README "Kern" owns the measurements.
#
# Stop and SubagentStop (README "Stop hook") are answered by the command wiring.toml binds to them,
# stop-check in the delivery component's process; where no command answers (no binary, no core,
# none bound, its process not attached yet, or it failed), work_tickets.py stop-check answers as a
# process of its own.
project="${CLAUDE_PROJECT_DIR:-$PWD}"
event="${1:-}"
bin=""
read -r bin 2>/dev/null <"$project/.se/.runtime/kern.path"
case "$event" in
Stop | SubagentStop) ;;
*)
  [ -n "$bin" ] && [ -x "$bin" ] || exit 0
  exec "$bin" hook "$event" --root "$project" 2>/dev/null
  ;;
esac
# The fallback's exit code from kern; the wait covers a stop-check that reads GitHub through gh.
unanswered=3
IFS= read -r -d '' payload
if [ -n "$bin" ] && [ -x "$bin" ]; then
  answer="$("$bin" hook "$event" --root "$project" --wait 10s --unanswered "$unanswered" 2>/dev/null <<<"$payload")"
  if [ $? -ne "$unanswered" ]; then
    [ -n "$answer" ] && printf '%s\n' "$answer"
    exit 0
  fi
fi
here="${BASH_SOURCE[0]%/*}"
[ "$here" = "${BASH_SOURCE[0]}" ] && here=.
# uv where bootstrap.sh installs it; --no-project so no project's environment is synced.
PATH="$HOME/.local/bin:$PATH" exec uv run --no-project --python ">=3.11" python "$here/work_tickets.py" stop-check <<<"$payload"
