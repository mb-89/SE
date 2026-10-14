#!/bin/sh
# The build recipe for se: Go runs in src/, which holds go.mod, and embeds the
# commit se is built from (src/cmd/se/commit.go). It builds to
# src/plugin/bin/se, or to the file its one argument names. RUNME.sh, CI and
# the skills run it; se itself builds through update.Build.
set -eu
src=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
out=${1:-$src/plugin/bin/se}
case $out in
  /*) ;;
  *) out=$PWD/$out ;;
esac
go -C "$src" build -ldflags "-X main.commit=$(git -C "$src" rev-parse HEAD)" -o "$out" ./cmd/se
