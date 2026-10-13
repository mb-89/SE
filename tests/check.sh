#!/bin/sh
# The one definition of green. The pre-push hook and CI both run this file.
set -eu
cd "$(dirname "$0")/.."
if ! command -v claude >/dev/null 2>&1; then
  echo "check: the claude CLI is missing; install it with npm i -g @anthropic-ai/claude-code" >&2
  exit 1
fi
echo "check: plugin validate"; claude plugin validate plugin
echo "check: marketplace validate"; claude plugin validate .
echo "check: plugin test"; claude plugin test plugin
