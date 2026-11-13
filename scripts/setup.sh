#!/bin/sh
# Installs se's git hooks (public-safety check) into a repository: se itself by default, or the
# repository given as the first argument, such as a project that uses se as a module. Also adds the
# public check's local list (.public-check.local, never checked in) to the repository's .gitignore,
# and sets the repository's commit identity as work_tickets.py sync does, so its first commit
# already carries it. Its git goes through se's git door (scripts/git_door.py).
set -eu
script="$(dirname "$0")/../.githooks/se-script"
se_root="$("$script" git_door.py -C "$(dirname "$0")/.." rev-parse --show-toplevel)"
repo="$("$script" git_door.py -C "${1:-$se_root}" rev-parse --show-toplevel)"
if [ "$repo" = "$se_root" ]; then
    hooks=.githooks
else
    hooks="$se_root/.githooks"
fi
"$script" git_door.py -C "$repo" config core.hooksPath "$hooks"
echo "core.hooksPath of $repo set to $hooks"
local_list=.public-check.local
ignore="$repo/.gitignore"
if ! grep -qxF -e "$local_list" -e "/$local_list" "$ignore" 2>/dev/null; then
    if [ -s "$ignore" ] && [ -n "$(tail -c 1 "$ignore")" ]; then
        echo >> "$ignore"
    fi
    echo "$local_list" >> "$ignore"
    echo "$local_list added to $ignore"
fi
"$se_root/.githooks/se-script" work_tickets.py identity --worktree "$repo"
