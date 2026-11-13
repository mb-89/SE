#!/usr/bin/env bash
# SE's hook for one session event: posts the host's hook JSON on stdin to kern, the core SE pins
# (kern/release.toml), as `kern hook <event>`, and prints kern's answer as the hook's output.
#
#   se_hook.sh <event>     run by the Claude Code plugin's hooks (scripts/se_plugin.py)
#
# It fails open: where kern's binary is not on this machine yet (bootstrap.sh fetches it) or no core
# answers, it prints nothing and exits 0. Builtins only up to the one exec, so a hook costs kern's
# own start; README "Kern" owns the measurements.
here="${BASH_SOURCE[0]%/*}"
version=""
while IFS= read -r line; do
  case $line in 'version = "'*) version="${line#version = \"}" && version="${version%%\"*}" ;; esac
done 2>/dev/null <"$here/../kern/release.toml"
bin="$HOME/.se/bin/kern-$version"
[ -x "$bin.exe" ] && bin="$bin.exe"
[ -n "$version" ] && [ -x "$bin" ] || exit 0
exec "$bin" hook "${1:-}" --root "${CLAUDE_PROJECT_DIR:-$PWD}" 2>/dev/null
