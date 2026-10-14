#!/bin/sh
# The one definition of green. The pre-push hook and CI both run this file.
set -eu
cd "$(dirname "$0")/.."
set --
. ./tests/tools.sh
# The battery needs the tools pinned there, so it installs whichever a box lacks.
if [ -n "$(tools_differ)" ]; then
  echo "check: installing the pinned tools ($(echo $(tools_differ)))"
  sh ./tests/tools.sh install
fi
differ=$(tools_differ)
if [ -n "$differ" ]; then
  echo "check: the pinned tools are not installed ($(echo $differ)) after sh tests/tools.sh install" >&2
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
# each Go test's to go test's events, what the plugin tests printed (each
# plugin test's duration among it), and the report reads them against
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

# dead fails on any function nothing reaches, the tests counted as callers:
# such code is deleted, not argued about (spec/overhaul.md, pruning).
dead() {
  out=$(within src deadcode -test ./...)
  [ -z "$out" ] && return
  echo "$out"
  echo "check: nothing reaches the functions above, not even a test: delete them" >&2
  return 1
}

step "se rules" go -C src run ./cmd/se rules --workspace "$PWD"
step "golangci-lint" within src golangci-lint run ./...
step "biome" within src/plugin biome check --error-on-warnings
step "deadcode" dead
step "go test" go -C src run ./cmd/battery gotest "$PWD" ./...
step "plugin validate" claude plugin validate src/plugin
step "marketplace validate" claude plugin validate .
step "plugin test" go -C src run ./cmd/battery plugintest "$PWD" "$PWD/src/plugin"
go -C src run ./cmd/battery report "$PWD"
