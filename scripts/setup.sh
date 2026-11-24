#!/bin/sh
# Installs se's git hooks (public-safety check) into a repository: se itself by default, or the
# repository given as the first argument, such as a project that uses se as a module. Also adds the
# public check's local list (.public-check.local, never checked in) to the repository's .gitignore,
# installs the merge driver of generated files (merge.se-generated), and sets the repository's
# commit identity as work_tickets.py sync does, so its first commit already carries it. Its git
# goes through se's git door (scripts/git_door.py). In se's own checkout it then installs obs's
# adapter component obs-html where it is missing, which the docs and decks build with
# (`build_docs.py --install-html`).
#
# With --copilot (opt-in) it then installs SE for GitHub Copilot there: `copilot.py install`
# (docs/copilot.md, "Another repository"). Without it nothing else changes.
set -eu
target=""
copilot=""
for arg in "$@"; do
    case "$arg" in
        --copilot) copilot=1 ;;
        *) target="$arg" ;;
    esac
done
script="$(dirname "$0")/../.githooks/se-script"
se_root="$("$script" git_door.py -C "$(dirname "$0")/.." rev-parse --show-toplevel)"
repo="$("$script" git_door.py -C "${target:-$se_root}" rev-parse --show-toplevel)"
if [ "$repo" = "$se_root" ]; then
    hooks=.githooks
else
    hooks="$se_root/.githooks"
fi
# The checkout's own hooks that stop running once core.hooksPath names se's are named first.
"$script" se_start.py stopped-hooks --repo "$repo" --hooks "$hooks"
"$script" git_door.py -C "$repo" config core.hooksPath "$hooks"
echo "core.hooksPath of $repo set to $hooks"
# The merge driver of the generated files a merge regenerates (.gitattributes merge=se-generated):
# it keeps our side, and the merge's commit hooks regenerate them (scripts/generated.py "The merge").
"$script" git_door.py -C "$repo" config merge.se-generated.name "a generated file: keep ours, the merge's commit hooks regenerate it"
"$script" git_door.py -C "$repo" config merge.se-generated.driver true
echo "merge driver se-generated of $repo set"
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
if [ "$repo" = "$se_root" ]; then
    "$se_root/.githooks/se-script" build_docs.py --install-html
fi
if [ -n "$copilot" ]; then
    "$se_root/.githooks/se-script" copilot.py install --repo "$repo"
fi
