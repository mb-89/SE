#!/bin/sh
# The battery's linters, pinned: one place for their versions. RUNME.sh, CI
# and tests/check.sh run `sh tests/tools.sh install`; check.sh sources this
# file and refuses any other version, so every machine lints alike.
# `sh tests/tools.sh fmt` (what `se fmt` runs) installs them the same way,
# then runs every formatter the battery checks.
GOLANGCI_LINT=2.5.0
BIOME=2.2.4

# tools_differ names each pinned linter that is missing or at another version.
tools_differ() {
  golangci-lint --version 2>/dev/null | grep -q "version $GOLANGCI_LINT " || echo "golangci-lint $GOLANGCI_LINT"
  [ "$(biome --version 2>/dev/null)" = "Version: $BIOME" ] || echo "biome $BIOME"
}

case ${1:-} in
install | fmt)
  set -eu
  PATH="$(go env GOPATH)/bin:$PATH"
  for tool in $(tools_differ | cut -d' ' -f1); do
    case $tool in
      golangci-lint) go install "github.com/golangci/golangci-lint/v2/cmd/golangci-lint@v$GOLANGCI_LINT" ;;
      biome)
        command -v npm >/dev/null 2>&1 || { echo "tools: npm is missing; install Node.js, then run this again" >&2; exit 1; }
        npm install -g "@biomejs/biome@$BIOME"
        ;;
    esac
  done
  ;;
esac

if [ "${1:-}" = fmt ]; then
  golangci-lint fmt ./...
  biome check --write
fi
