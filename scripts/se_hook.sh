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
#
# A late checkout (README "Cloud sessions"): where the hook's JSON names a working directory inside
# another git checkout than the project, with an se.toml and no binary named for it yet (cloned after
# the session's start, so SessionStart never ran for it), the first hook there starts it as
# SessionStart would have, `bootstrap.sh --hook` for that checkout in the background, claimed once
# per ten minutes; once it has named its binary, the hooks post to that checkout's core.
project="${CLAUDE_PROJECT_DIR:-$PWD}"
event="${1:-}"
here="${BASH_SOURCE[0]%/*}"
[ "$here" = "${BASH_SOURCE[0]}" ] && here=.
IFS= read -r -d '' payload
checkout=""
if [[ $payload =~ \"cwd\"[[:space:]]*:[[:space:]]*\"([^\"]*)\" ]]; then
  dir="${BASH_REMATCH[1]//\\\\/\\}"
  while [ -n "$dir" ]; do
    if [ -e "$dir/.git" ]; then
      [ -f "$dir/se.toml" ] && checkout="$dir"
      break
    fi
    up="${dir%[/\\]*}"
    [ "$up" = "$dir" ] && break
    dir="$up"
  done
fi
if [ -n "$checkout" ] && [ "$checkout" != "$project" ]; then
  if [ -f "$checkout/.se/.runtime/kern.path" ]; then
    project="$checkout"
  else
    claim="$checkout/.se/.runtime/late-start.claim"
    if mkdir -p "$checkout/.se/.runtime" 2>/dev/null &&
      { [ ! -e "$claim" ] || [ -z "$(find "$claim" -mmin -10 2>/dev/null)" ]; } &&
      rm -f "$claim" && (set -C && : >"$claim") 2>/dev/null; then
      detach=()
      command -v setsid >/dev/null 2>&1 && detach=(setsid)
      CLAUDE_PROJECT_DIR="$checkout" ${detach[@]+"${detach[@]}"} bash "$here/bootstrap.sh" --hook \
        <<<"$payload" >/dev/null 2>&1 &
    fi
  fi
fi
bin=""
read -r bin 2>/dev/null <"$project/.se/.runtime/kern.path"
case "$event" in
Stop | SubagentStop) ;;
*)
  [ -n "$bin" ] && [ -x "$bin" ] || exit 0
  exec "$bin" hook "$event" --root "$project" 2>/dev/null <<<"$payload"
  ;;
esac
# The fallback's exit code from kern; the wait covers a stop-check that reads GitHub through gh.
unanswered=3
if [ -n "$bin" ] && [ -x "$bin" ]; then
  answer="$("$bin" hook "$event" --root "$project" --wait 10s --unanswered "$unanswered" 2>/dev/null <<<"$payload")"
  if [ $? -ne "$unanswered" ]; then
    [ -n "$answer" ] && printf '%s\n' "$answer"
    exit 0
  fi
fi
# uv where bootstrap.sh installs it; --no-project so no project's environment is synced.
PATH="$HOME/.local/bin:$PATH" exec uv run --no-project --python ">=3.11" python "$here/work_tickets.py" stop-check <<<"$payload"
