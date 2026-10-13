#!/bin/sh
# Refuses a Bash call that skips the repo's git hooks. Exit 2 blocks the call.
input=$(cat)
case "$input" in
  *--no-verify*|*core.hooksPath=*)
    echo "Blocked: SE runs its hooks. Run sh ./check.sh and fix what it reports." >&2
    exit 2 ;;
esac
exit 0
