#!/bin/sh
# Regroups the bare open se issues into manifests once, the migration of #371 (all work moves in manifests): each line of the plan is "Title|n,n,n".
# Usage: sh src/scripts/regroup-into-manifests.sh PLAN [SE]
# Each line makes a new manifest with se issue new --manifest, titled Title,
# and makes each issue n its sub-issue through GitHub's sub-issues API. One
# request at a time, as the owner's account is near its rate limit.
set -eu
plan=$1
se=${2:-./src/plugin/bin/se}
repo=$(git remote get-url origin | sed -E 's#.*[/:]([^/]+/[^/]+)$#\1#; s#\.git$##')
while IFS='|' read -r title numbers; do
  [ -z "$title" ] && continue
  body=$(printf 'A manifest of the migration of #371: the bare open issues on one topic, regrouped.\n\nIts leaves: %s.' "$(echo "$numbers" | sed 's/,/, #/g; s/^/#/')")
  made=$("$se" issue new --manifest --title "$title" --body "$body" --blocked-by none --json | jq -r .number)
  echo "#$made $title"
  for n in $(echo "$numbers" | tr ',' ' '); do
    id=$(gh api "repos/$repo/issues/$n" --jq .id) # se: around-the-door - the one migration of #371, run once; se has no command that files an existing issue into a manifest
    gh api -X POST "repos/$repo/issues/$made/sub_issues" -F "sub_issue_id=$id" --silent # se: around-the-door - the one migration of #371, run once; se has no command that files an existing issue into a manifest
    echo "  #$n"
  done
done <"$plan"
