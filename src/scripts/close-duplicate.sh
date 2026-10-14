#!/bin/sh
# Closes se issue DUP as a duplicate of KEPT with a comment on each linking the other, and notes it on EVIDENCE, since no se command closes a duplicate (#250).
# Usage: sh src/scripts/close-duplicate.sh OWNER/NAME DUP KEPT [EVIDENCE]
set -eu
repo=$1 dup=$2 kept=$3 evidence=${4:-}
gh api "repos/$repo/issues/$dup/comments" -f body="Duplicate of #$kept, which asks for the same fix and is the wider one." >/dev/null
gh api "repos/$repo/issues/$kept/comments" -f body="#$dup was closed as a duplicate of this issue." >/dev/null
if [ -n "$evidence" ]; then
  gh api "repos/$repo/issues/$evidence/comments" -f body="Evidence: #$dup and #$kept were open at once asking for the same fix; #$dup was closed as a duplicate of #$kept." >/dev/null
fi
gh api -X PATCH "repos/$repo/issues/$dup" -f state=closed -f state_reason=duplicate --jq '"#\(.number) \(.state) \(.state_reason)"'
