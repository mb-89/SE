#!/usr/bin/env bash
# The launcher of SE's MCP door (`se mcp`, README "MCP door"): what a host's MCP configuration runs.
# Standalone: it reads nothing of SE but the release pin, components/release.toml, beside it.
#
#   se_mcp.sh --root <project>
#
# Standard output carries MCP alone; everything else goes to <project>/.se/.runtime/mcp.log (else
# the system's temporary folder). The binary is the one SE's start puts in place,
# ~/.se/bin/se-<pinned version>, run as `se mcp --root <project> --home <this SE>`: a project with
# no wiring of its own is served SE's (kern's cli.Source). SE_MCP_BIN names a local binary instead.
#
# Where the binary is missing, the launcher answers at once as a door of its own: one tool, status,
# whose every call says "not installed" and names the setup to run, SE's start (bootstrap.sh),
# which fetches the binary and checks it against the release's SHA256SUMS in ~/.se/bin. It fetches
# nothing itself, so the host never waits on a download. Its twin is se_mcp.ps1.
set -u
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
se_root="${here%/*}"
root=""
while [ $# -gt 0 ]; do
  case "$1" in
    --root) root="${2:-}"; shift; [ $# -gt 0 ] && shift ;;
    --root=*) root="${1#--root=}"; shift ;;
    *) shift ;;
  esac
done
[ -n "$root" ] || root="$PWD"
root="$(cd "$root" 2>/dev/null && pwd)" || root="$PWD"

log="$root/.se/.runtime/mcp.log"
mkdir -p "${log%/*}" 2>/dev/null && : >>"$log" 2>/dev/null || log="${TMPDIR:-/tmp}/se-mcp.log"
note() { printf '%s se_mcp.sh: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >>"$log" 2>/dev/null; }

version="$(sed -n 's/^version[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' "$se_root/components/release.toml" 2>/dev/null | head -n 1)"
suffix=""
case "$(uname -s 2>/dev/null)" in MINGW* | MSYS* | CYGWIN*) suffix=".exe" ;; esac
bin="${SE_MCP_BIN:-}"
[ -n "$bin" ] || bin="$HOME/.se/bin/se-$version$suffix"
sums="$HOME/.se/bin/se-$version.SHA256SUMS"

if [ -n "$version${SE_MCP_BIN:-}" ] && [ -x "$bin" ]; then
  note "starting $bin mcp --root $root --home $se_root"
  exec "$bin" mcp --root "$root" --home "$se_root" 2>>"$log"
fi

# The binary is missing: answer as a door of one tool.
if [ -z "$version" ]; then
  why="no release pin at $se_root/components/release.toml"
elif [ -n "${SE_MCP_BIN:-}" ]; then
  why="SE_MCP_BIN names $bin, which is no executable"
elif [ -f "$sums" ]; then
  why="se $version is not in place at $bin yet; SE's start found its release and fetches it"
else
  why="se $version is not in place at $bin"
fi
remedy="run setup in the project: cd '$root' && bash '$se_root/scripts/bootstrap.sh' --hook </dev/null, then restart the se MCP server"
note "not installed: $why"
json() { # <text>: the text as a JSON string's content
  local s="$1"
  s="${s//\\/\\\\}"
  s="${s//\"/\\\"}"
  s="${s//$'\t'/ }"
  printf '%s' "$s"
}
message="$(json "$why")"
remedy="$(json "$remedy")"
answer() { printf '{"jsonrpc":"2.0","id":%s,%s}\n' "$1" "$2"; }
while IFS= read -r line || [ -n "$line" ]; do
  [[ $line =~ \"method\"[[:space:]]*:[[:space:]]*\"([^\"]+)\" ]] || continue
  method="${BASH_REMATCH[1]}"
  [[ $line =~ \"id\"[[:space:]]*:[[:space:]]*(\"[^\"]*\"|-?[0-9]+) ]] || continue # a notification
  id="${BASH_REMATCH[1]}"
  case "$method" in
    initialize)
      protocol="2025-06-18"
      [[ $line =~ \"protocolVersion\"[[:space:]]*:[[:space:]]*\"([^\"]+)\" ]] && protocol="${BASH_REMATCH[1]}"
      answer "$id" "\"result\":{\"protocolVersion\":\"$protocol\",\"capabilities\":{\"tools\":{}},\"serverInfo\":{\"name\":\"se\",\"version\":\"$(json "$version")\"},\"instructions\":\"not-installed: $message. Remedy: $remedy.\"}"
      ;;
    tools/list)
      answer "$id" '"result":{"tools":[{"name":"status","title":"status","description":"Whether SE'"'"'s core runs. SE'"'"'s binary is not installed here: every call says what to run.","inputSchema":{"type":"object","properties":{},"additionalProperties":false},"annotations":{"readOnlyHint":true}}]}'
      ;;
    tools/call)
      answer "$id" "\"result\":{\"isError\":true,\"content\":[{\"type\":\"text\",\"text\":\"not-installed: $message. Remedy: $remedy.\"}],\"structuredContent\":{\"error\":\"not-installed\",\"message\":\"$message\",\"remedy\":\"$remedy\"}}"
      ;;
    ping) answer "$id" '"result":{}' ;;
    *) answer "$id" "\"error\":{\"code\":-32601,\"message\":\"se_mcp.sh offers no $(json "$method") while SE's binary is not installed\"}" ;;
  esac
done
