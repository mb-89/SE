#!/bin/sh
# Installs SE for this user: installs every tool SE needs that is missing
# (tests/tools.sh pins them, and puts them under ~/.se without admin rights),
# builds se, and makes this checkout the marketplace "se", so the plugin se
# loads in every Claude session on this machine. Run it again any time; it
# changes nothing that already stands. Run it from the checkout that should
# stay on main: /se update keeps that one current, and the sessions you work
# in run it. It runs on Linux, macOS and Windows under Git Bash.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

for tool in git curl tar; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "RUNME: $tool is missing; it comes with every system SE runs on (Git Bash on Windows), so install it first" >&2
    exit 1
  fi
done
sh "$root/tests/tools.sh" install
set --
. "$root/tests/tools.sh"
git -C "$root" config core.hooksPath .githooks
sh "$root/src/build.sh"
if ! claude plugin marketplace list 2>/dev/null | grep -q "$root"; then
  claude plugin marketplace add "$root"
fi
if ! claude plugin list 2>/dev/null | grep -q "se@se"; then
  claude plugin install se@se --scope user
fi
# The plugin, the daemon, /se on and /se ui need no GitHub; the fleet's
# commands call GitHub's REST API with gh's token. On a cloud box the proxy
# adds the credentials, with no login of its own. The login never blocks the
# install.
if ! gh auth status >/dev/null 2>&1 && ! gh api rate_limit >/dev/null 2>&1; then
  if [ -t 0 ] && [ -t 1 ]; then
    gh auth login || true
  fi
  if ! gh auth status >/dev/null 2>&1; then
    echo "RUNME: gh is not signed in to GitHub. se issue, se briefing, se fleet, the retro and the overhaul need it: run gh auth login before you use them."
  fi
fi
echo "RUNME: SE is installed. Open a new terminal (or run: . ~/.bashrc), start a session and type /se on; /se help lists the rest."
