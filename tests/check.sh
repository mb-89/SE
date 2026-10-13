#!/bin/sh
# The one definition of green. The pre-push hook and CI both run this file.
set -eu
cd "$(dirname "$0")/.."
set --
. ./tests/tools.sh
PATH="$(go env GOPATH 2>/dev/null)/bin:$PATH"
for tool in go claude golangci-lint biome; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "check: $tool is missing; RUNME.sh names what SE needs" >&2
    exit 1
  fi
done
differ=$(tools_differ)
if [ -n "$differ" ]; then
  echo "check: the pinned linters are not installed ($(echo $differ)); run sh tests/tools.sh install" >&2
  exit 1
fi

now() {
  t=$(date +%s%N)
  case $t in
    *N) echo $(($(date +%s) * 1000)) ;;
    *) echo $((t / 1000000)) ;;
  esac
}
# step runs one check and reports how long it took.
step() {
  name=$1
  shift
  echo "check: $name"
  start=$(now)
  "$@"
  echo "check: $name took $(($(now) - start))ms"
}

step "se rules" go run ./src/cmd/se rules
step "golangci-lint" golangci-lint run ./...
step "biome" biome check --error-on-warnings
step "go test" go test ./...
step "plugin validate" claude plugin validate src/plugin
step "marketplace validate" claude plugin validate .
step "plugin test" claude plugin test src/plugin
