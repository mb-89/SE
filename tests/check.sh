#!/bin/sh
# The one definition of green. The pre-push hook and CI both run this file.
set -eu
cd "$(dirname "$0")/.."
set --
. ./tests/tools.sh
PATH="$(go env GOPATH 2>/dev/null)/bin:$PATH"
for tool in go claude; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "check: $tool is missing; RUNME.sh names what SE needs" >&2
    exit 1
  fi
done
# Only the battery needs the pinned linters, so it installs whichever a box lacks.
if [ -n "$(tools_differ)" ]; then
  echo "check: installing the pinned linters ($(echo $(tools_differ)))"
  sh ./tests/tools.sh install
fi
differ=$(tools_differ)
if [ -n "$differ" ]; then
  echo "check: the pinned linters are not installed ($(echo $differ)) after sh tests/tools.sh install" >&2
  exit 1
fi

now() {
  t=$(date +%s%N)
  case $t in
    *N) echo $(($(date +%s) * 1000)) ;;
    *) echo $((t / 1000000)) ;;
  esac
}
# The battery profiles itself: each step's duration goes to the steps file,
# each Go test's to go test's events, and the report reads both against
# spec/budgets.yaml (src/cmd/battery).
battery=.se/.runtime/battery
rm -rf "$battery"
mkdir -p "$battery"
# step runs one check and reports how long it took.
step() {
  name=$1
  shift
  echo "check: $name"
  start=$(now)
  "$@"
  took=$(($(now) - start))
  echo "check: $name took ${took}ms"
  printf '%s\t%s\n' "$name" "$took" >>"$battery/steps.tsv"
}

# within runs a command in a folder: golangci-lint in src/, which holds go.mod, and
# biome in src/plugin, which holds its configuration. Go itself takes -C src.
within() (
  cd "$1"
  shift
  "$@"
)

step "se rules" go -C src run ./cmd/se rules --workspace "$PWD"
step "golangci-lint" within src golangci-lint run ./...
step "biome" within src/plugin biome check --error-on-warnings
step "go test" go -C src run ./cmd/battery gotest "$PWD" ./...
step "plugin validate" claude plugin validate src/plugin
step "marketplace validate" claude plugin validate .
step "plugin test" claude plugin test src/plugin
go -C src run ./cmd/battery report "$PWD"
