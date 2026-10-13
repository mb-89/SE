#!/bin/sh
# Installs SE for this user: this checkout becomes the marketplace "se", and
# the plugin se loads in every Claude session on this machine. Run it again
# any time; it changes nothing that already stands. After editing the plugin,
# /reload-plugins in a session picks the change up, since the plugin is read
# from this folder.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if ! command -v claude >/dev/null 2>&1; then
  echo "RUNME: the claude CLI is missing; install Claude Code first" >&2
  exit 1
fi
git -C "$root" config core.hooksPath .githooks
if ! claude plugin marketplace list 2>/dev/null | grep -q "$root"; then
  claude plugin marketplace add "$root"
fi
if ! claude plugin list 2>/dev/null | grep -q "se@se"; then
  claude plugin install se@se --scope user
fi
echo "RUNME: SE is installed. Start a session and type /se-on."
