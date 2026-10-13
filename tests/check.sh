#!/bin/sh
# The one definition of green. The pre-push hook and CI both run this file.
set -eu
cd "$(dirname "$0")/.."
for tool in go claude; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "check: $tool is missing; RUNME.sh names what SE needs" >&2
    exit 1
  fi
done
echo "check: gofmt"; unformatted=$(gofmt -l .); [ -z "$unformatted" ] || { echo "$unformatted" >&2; exit 1; }
echo "check: go vet"; go vet ./...
echo "check: go test"; go test ./...
echo "check: plugin validate"; claude plugin validate plugin
echo "check: marketplace validate"; claude plugin validate .
echo "check: plugin test"; claude plugin test plugin
