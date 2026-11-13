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
project="${CLAUDE_PROJECT_DIR:-$PWD}"
bin=""
read -r bin 2>/dev/null <"$project/.se/.runtime/kern.path"
[ -n "$bin" ] && [ -x "$bin" ] || exit 0
exec "$bin" hook "${1:-}" --root "$project" 2>/dev/null
