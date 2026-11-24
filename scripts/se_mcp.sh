#!/usr/bin/env bash
# The launcher of SE's MCP door (`se mcp`, docs/start.md "The MCP door"): what a host's MCP configuration runs.
# Standalone: it reads nothing of SE but the release pin, components/release.toml, beside it.
#
#   se_mcp.sh --root <project>
#
# Standard output carries MCP alone; everything else goes to <project>/.se/.runtime/mcp.log (else
# the system's temporary folder), and in a plugin install whose session folder has no .git in it or
# above it, to ~/.se/.runtime/mcp.log instead, so that folder gets no .se. The binary is the one SE's start puts in place,
# ~/.se/bin/se-<pinned version>, run as `se mcp --root <project> --home <this SE>`: a project with
# no wiring of its own is served SE's (kern's cli.Source). SE_MCP_BIN names a local binary instead.
#
# Where the binary is missing, the launcher answers at once as a door of its own: one tool, status,
# whose every call says "not installed" and names the setup to run, SE's start (bootstrap.sh),
# which fetches the binary and checks it against the release's SHA256SUMS in ~/.se/bin. It fetches
# nothing itself, so the host never waits on a download. Its twin is se_mcp.ps1.
#
# A plugin install (Copilot's plugin config runs this from the plugin folder with --root .): only
# where the plugin's root, this SE and --root are one physical folder, the launcher serves the
# session's repository instead. The plugin's root is Copilot's PLUGIN_ROOT, else Claude Code's
# CLAUDE_PLUGIN_ROOT. It reads SE_SESSION_CWD, else the host's session folder (Copilot's
# COPILOT_SESSION_CWD, Claude Code's CLAUDE_PROJECT_DIR; an absolute existing folder; each counts
# only under its own host), else, on Linux and macOS, its parent's working directory; walks up to the nearest .git;
# hands over to that repository's own launcher where it is an SE checkout; and writes one line,
# "plugin <folder>: root <root> from <source>", to the chosen root's mcp.log (the home log where
# that root is a session folder with no .git). Where no source
# counts and the plugin folder is no checkout, SE_MCP_PLUGIN_FOLDER names it to the binary.
# SE_MCP_PLUGIN_PROJECT=off keeps the plugin folder as the root.
set -u
[ -n "${HOME+x}" ] || { HOME="$(cd ~ 2>/dev/null && pwd)"; export HOME; }
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

log_folder() { # <root> <session folder: 1 or 0> <home>: the folder the launcher logs in
  if [ "$2" = 1 ]; then printf '%s' "$3/.se/.runtime"; else printf '%s' "$1/.se/.runtime"; fi
}
session_folder() { # <root> <plugin folder>: 1 where the plugin case's root is a session folder, no checkout
  if [ "$1" != "$2" ] && [ ! -e "$1/.git" ]; then printf 1; else printf 0; fi
}
logfile() { # <root> [<session folder: 1 or 0>]: the log the launcher writes for that root
  local log
  log="$(log_folder "$1" "${2:-0}" "$HOME")/mcp.log"
  mkdir -p "${log%/*}" 2>/dev/null && : >>"$log" 2>/dev/null || log="${TMPDIR:-/tmp}/se-mcp.log"
  printf '%s' "$log"
}
note() { printf '%s se_mcp.sh: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >>"$log" 2>/dev/null; }
# A folder's physical path, one name per folder: on Windows by its drive (/c/...), as MSYS names a
# folder entered by its Windows path by its mount table instead (the temporary folder as /tmp).
phys() { # <folder>
  local p w
  p="$(cd "$1" 2>/dev/null && pwd -P)" || return 1
  if w="$(cd "$1" && pwd -W 2>/dev/null)" && [[ "$w" =~ ^([A-Za-z]):(/.*)?$ ]]; then
    p="/${BASH_REMATCH[1],,}${BASH_REMATCH[2]}"
  fi
  printf '%s' "$p"
}

plugin_project() { # <plugin folder> <session variables>: the root a plugin install serves; fails where no source counts
  local plugin="$1" names="$2" name value dir="" source="" found=0
  usable() { case "$1" in /* | [A-Za-z]:[\\/]*) [ -d "$1" ] ;; *) false ;; esac; }
  for name in $names; do
    value="${!name:-}"
    if usable "$value"; then dir="$(phys "$value")" && { source="$name=$value"; break; }; fi
  done
  if [ -z "$source" ]; then
    value=""
    case "$(uname -s 2>/dev/null)" in
      Linux) value="$(cd -P "/proc/$PPID/cwd" 2>/dev/null && pwd -P)" ;;
      Darwin) value="$(lsof -a -p "$PPID" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1)" ;;
    esac
    if usable "$value" && dir="$(phys "$value")"; then
      case "$dir/" in "$plugin/"*) dir="" ;; *) source="parent cwd $value" ;; esac
    fi
  fi
  local chosen="$plugin"
  if [ -n "$source" ]; then
    found=1
    case "$dir/" in
      "$plugin/"*) ;;
      *)
        chosen="$dir"
        while [ ! -e "$chosen/.git" ]; do
          case "$chosen" in /) chosen="$dir"; break ;; esac
          chosen="${chosen%/*}"
          [ -n "$chosen" ] || chosen=/
        done
        ;;
    esac
  else
    source="no variable set (${names// /, }) and no parent cwd outside the plugin"
  fi
  log="$(logfile "$chosen" "$(session_folder "$chosen" "$plugin")")"
  note "plugin $plugin: root $chosen from $source"
  printf '%s' "$chosen"
  [ "$found" = 1 ]
}

session=0
plugin_root="${PLUGIN_ROOT:-}" session_names="SE_SESSION_CWD COPILOT_SESSION_CWD"
if [ -z "$plugin_root" ] && [ -n "${CLAUDE_PLUGIN_ROOT:-}" ]; then
  plugin_root="$CLAUDE_PLUGIN_ROOT" session_names="SE_SESSION_CWD CLAUDE_PROJECT_DIR"
fi
if [ -n "$plugin_root" ] && [ "${SE_MCP_PLUGIN_PROJECT:-}" != off ]; then
  plugin="$(phys "$plugin_root")" || plugin=""
  if [ -n "$plugin" ] && [ "$plugin" = "$(phys "$se_root")" ] && [ "$plugin" = "$(phys "$root")" ]; then
    unset SE_MCP_PLUGIN_FOLDER
    if chosen="$(plugin_project "$plugin" "$session_names")"; then
      if [ "$chosen" != "$plugin" ]; then
        root="$chosen"
        session="$(session_folder "$chosen" "$plugin")"
        if [ -f "$chosen/scripts/se_mcp.sh" ] && [ -f "$chosen/components/release.toml" ]; then
          exec "${BASH:-bash}" "$chosen/scripts/se_mcp.sh" --root "$chosen"
        fi
      fi
    elif [ ! -e "$plugin/.git" ]; then
      export SE_MCP_PLUGIN_FOLDER="$plugin"
    fi
  fi
fi

log="$(logfile "$root" "$session")"

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
