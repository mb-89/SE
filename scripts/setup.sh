#!/bin/sh
# Installs se's git hooks (public-safety check) into a repository: se itself by default, or the
# repository given as the first argument, such as a project that uses se as a module.
set -eu
se_root="$(git -C "$(dirname "$0")/.." rev-parse --show-toplevel)"
repo="$(git -C "${1:-$se_root}" rev-parse --show-toplevel)"
if [ "$repo" = "$se_root" ]; then
    hooks=.githooks
else
    hooks="$se_root/.githooks"
fi
git -C "$repo" config core.hooksPath "$hooks"
echo "core.hooksPath of $repo set to $hooks"
