#!/bin/sh
# Installs SE for this user: builds se, installs the debugger, and makes this
# checkout the marketplace "se", so the plugin se loads in every Claude session
# on this machine. Run it again any time; it changes nothing that already
# stands. Run it from the checkout that should stay on main: /se update keeps
# that one current, and the sessions you work in run it.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# The debugger the VS Code launch configuration drives, pinned.
DLV=v1.25.2

for tool in claude go git; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "RUNME: $tool is missing; install it first" >&2
    exit 1
  fi
done
# se issue reads GitHub through gh, which owns the authentication. On a cloud
# box gh reaches the API without a login of its own.
if ! command -v gh >/dev/null 2>&1; then
  echo "RUNME: gh is missing; install it from https://cli.github.com (brew install gh, winget install GitHub.cli, or your distribution's gh package)" >&2
  exit 1
fi
if ! gh auth status >/dev/null 2>&1 && ! gh api rate_limit >/dev/null 2>&1; then
  echo "RUNME: gh cannot reach GitHub; run gh auth login, then RUNME.sh again" >&2
  exit 1
fi
git -C "$root" config core.hooksPath .githooks
(cd "$root" && go build -ldflags "-X main.commit=$(git rev-parse HEAD)" -o src/plugin/bin/se ./src/cmd/se)
if ! command -v dlv >/dev/null 2>&1 && [ ! -x "$(go env GOPATH)/bin/dlv" ]; then
  go install "github.com/go-delve/delve/cmd/dlv@$DLV"
fi
if ! claude plugin marketplace list 2>/dev/null | grep -q "$root"; then
  claude plugin marketplace add "$root"
fi
if ! claude plugin list 2>/dev/null | grep -q "se@se"; then
  claude plugin install se@se --scope user
fi
echo "RUNME: SE is installed. Start a session and type /se on; /se help lists the rest."
