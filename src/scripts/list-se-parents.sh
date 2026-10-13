# Needed to find a real tree on mb-89/SE to run `se review brief` on for #67's PR: lists every se issue with sub-issues, and how many of them are closed.
set -eu
repo=${1:-mb-89/SE}
gh api --paginate "repos/$repo/issues?state=all&labels=se&per_page=100" \
  --jq '.[] | select(.sub_issues_summary.total>0) | "#\(.number) \(.state) \(.sub_issues_summary.completed)/\(.sub_issues_summary.total) closed  \([.labels[].name]|join(","))  \(.title)"'
