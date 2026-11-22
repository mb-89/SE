#!/usr/bin/env bash
# SE's hook for one session event: posts the host's hook JSON on stdin to kern, the core SE pins, as
# `kern hook <event>`, and prints kern's answer as the hook's output.
#
#   se_hook.sh <event>     run by the Claude Code plugin's hooks (scripts/se_plugin.py)
#
# The binary is the one bootstrap.sh named for the project at the session's start, in
# <project>/.se/.runtime/kern.path. It fails open: where that names no binary on this machine yet or
# no core answers, it prints nothing and exits 0. Builtins only up to the one exec, so a hook costs
# kern's own start; README "Kern" owns the measurements.
#
# Stop and SubagentStop (README "Stop hook") are answered by the command wiring.toml binds to them,
# stop-check in the delivery component's process; where no command answers (no binary, no core,
# none bound, its process not attached yet, or it failed), work_tickets.py stop-check answers as a
# process of its own.
#
# A late checkout (README "Cloud sessions"): where the hook's JSON names a working directory inside
# another git checkout than the project, with an se.toml and no binary named for it yet (cloned after
# the session's start, so SessionStart never ran for it), the first hook there starts it as
# SessionStart would have, `bootstrap.sh --hook` for that checkout in the background, claimed once
# per ten minutes; once it has named its binary, the hooks post to that checkout's core.
#
# Under Copilot (docs/copilot.md "What a session costs"), a Stop's payload carries the host field
# SE_PAYLOAD_HOST names, so the delivery check advises rather than refuses there unless se.toml
# `[copilot] refuse_stop` is true; a check that advises answers a `systemMessage`, which Copilot's
# stop hook does not read, so its text goes to stderr with exit code 2, which Copilot shows the
# person as a warning and the run goes on.
#
# The form gate (README "Forms"): a PreToolUse whose tool is one of SE's guarded GitHub writes
# (GATE_TOOLS below, the table of scripts/se_forms.py's docstring) runs `se_forms.py gate` with the
# payload, through uv without a Python download, else python3 where it is 3.11 or later; its answer,
# a JSON deny or nothing, is the hook's whole stdout, and kern still gets the payload, its answer
# discarded. The gate also runs for a shell call: a tool whose input holds a string `command`,
# `input` or `script` in which `gh` stands as a word followed by a space (shelled below), so
# `se_forms.py gate` reads its gh writes (its docstring: The shell reader). The tests are builtins
# only, so every other call costs what it did. SE_FORMS_GATE=off skips it.
# Where the project's se.toml `[forms] files` is `write`, which SE's start leaves as the line
# `write` in <project>/.se/.runtime/forms-files (scripts/bootstrap.sh), the gate also runs for
# Claude Code's Write, Edit and MultiEdit of a file in the project and for the GitHub tools that
# write files (FILE_TOOLS, GITHUB_FILE_TOOLS: its docstring, The file tools); without that line
# they cost what they did.
#
# Under Copilot (SE_HOOK_HOST=copilot, which its hooks files set, or a camelCase payload), a PreToolUse
# posts nothing to kern, which has never had those events from Copilot: a guarded call runs the gate
# alone, told the host so it answers in Copilot's shape, and every other call ends after the builtin
# tests. Copilot's hooks files register PreToolUse only where the build reads `[forms] gate` as on
# (scripts/se_plugin.py `copilot_hooks`).
#
# Either host (scripts/hosts.sh, the host table): the payload may be Claude Code's (snake_case) or
# Copilot's (camelCase); kern and stop-check get it in snake_case. The project is the host's project
# variable, else the checkout holding the payload's cwd, else the working directory.
event="${1:-}"
here="${BASH_SOURCE[0]%/*}"
[ "$here" = "${BASH_SOURCE[0]}" ] && here=.
IFS= read -r -d '' payload
# shellcheck source=hosts.sh
. "$here/hosts.sh"
se_payload "$payload"
payload="$se_payload_text"
se_project "$payload"
project="$se_project"
# SE_HOOK_CORE=off in the environment (README "Machine-local `~/.se/local.toml`"): no late checkout
# is started, kern.path is not read and no core is posted to, so every event but Stop and
# SubagentStop ends here quietly and those go to stop-check. Off through the local file, the
# session's start left no kern.path (scripts/bootstrap.sh), so the hooks answer as without a binary.
core=true
if [ -n "${SE_HOOK_CORE+set}" ]; then
  case "$SE_HOOK_CORE" in [oO][fF][fF]) core=false ;; esac
fi
checkout=""
if $core && [[ $payload =~ \"cwd\"[[:space:]]*:[[:space:]]*\"([^\"]*)\" ]]; then
  dir="${BASH_REMATCH[1]//\\\\/\\}"
  while [ -n "$dir" ]; do
    if [ -e "$dir/.git" ]; then
      [ -f "$dir/se.toml" ] && checkout="$dir"
      break
    fi
    up="${dir%[/\\]*}"
    [ "$up" = "$dir" ] && break
    dir="$up"
  done
fi
if [ "$se_project_from" = cwd ]; then
  # No project variable: the session's start ran for the checkout holding the cwd.
  [ -n "$checkout" ] && project="$checkout"
elif [ -n "$checkout" ] && [ "$checkout" != "$project" ]; then
  if [ -f "$checkout/.se/.runtime/kern.path" ]; then
    project="$checkout"
  else
    claim="$checkout/.se/.runtime/late-start.claim"
    if mkdir -p "$checkout/.se/.runtime" 2>/dev/null &&
      { [ ! -e "$claim" ] || [ -z "$(find "$claim" -mmin -10 2>/dev/null)" ]; } &&
      rm -f "$claim" && (set -C && : >"$claim") 2>/dev/null; then
      detach=()
      command -v setsid >/dev/null 2>&1 && detach=(setsid)
      CLAUDE_PROJECT_DIR="$checkout" ${detach[@]+"${detach[@]}"} bash "$here/bootstrap.sh" --hook \
        <<<"$payload" >/dev/null 2>&1 &
    fi
  fi
fi
bin=""
$core && read -r bin 2>/dev/null <"$project/.se/.runtime/kern.path"
GATE_TOOLS=(issue_write add_issue_comment update_issue_comment create_pull_request update_pull_request
  pull_request_review_write add_comment_to_pending_review add_reply_to_pull_request_comment)
# Whether the payload's tool is a guarded GitHub write: its last part after `__` (Claude Code,
# a plugin's server too), else `/` (VS Code) or `-` (Copilot CLI), one of GATE_TOOLS, and its server
# part, or the payload's mcp_server.name, holding github. Builtins only.
guarded() { # <payload> [tool ...]: the tools, GATE_TOOLS where none is given
  local name server tool known
  [[ $1 =~ \"tool_name\"[[:space:]]*:[[:space:]]*\"([^\"]*)\" ]] || return 1
  name="${BASH_REMATCH[1]}"
  if [[ $name == mcp__*__* ]]; then
    server="${name#mcp__}"
    tool="${server##*__}"
    server="${server%__*}"
  elif [[ $name == */* ]]; then
    tool="${name##*/}" server="${name%/*}"
  elif [[ $name == *-* ]]; then
    tool="${name##*-}" server="${name%-*}"
  else
    return 1
  fi
  if [[ $1 =~ \"mcp_server\"[[:space:]]*:[[:space:]]*\{[^}]*\"name\"[[:space:]]*:[[:space:]]*\"([^\"]*)\" ]]; then
    server="${BASH_REMATCH[1]}"
  fi
  [[ $server == *[gG][iI][tT][hH][uU][bB]* ]] || return 1
  shift
  [ $# -gt 0 ] || set -- "${GATE_TOOLS[@]}"
  for known in "$@"; do
    [ "$tool" = "$known" ] && return 0
  done
  return 1
}
FILE_TOOLS=(Write Edit MultiEdit)
GITHUB_FILE_TOOLS=(push_files create_or_update_file)
# Whether the payload is a file tool's call the gate judges: only where the start left `write` in
# forms-files; Claude Code's own file tools by their whole name, whose file_path lies in the
# project, and the GitHub file tools as guarded reads them. Builtins only.
files_write=false
if [ "$event" = PreToolUse ] && read -r level 2>/dev/null <"$project/.se/.runtime/forms-files" &&
  [ "${level%$'\r'}" = write ]; then
  files_write=true
fi
filed() { # <payload>
  $files_write || return 1
  local name path known
  [[ $1 =~ \"tool_name\"[[:space:]]*:[[:space:]]*\"([^\"]*)\" ]] || return 1
  name="${BASH_REMATCH[1]}"
  for known in "${FILE_TOOLS[@]}"; do
    [ "$name" = "$known" ] || continue
    [[ $1 =~ \"file_path\"[[:space:]]*:[[:space:]]*\"(([^\"\\]|\\.)*)\" ]] || return 1
    path="${BASH_REMATCH[1]//\\\\/\\}"
    [[ $path == "$project"/* || $path == "$project"\\* ]]
    return
  done
  guarded "$1" "${GITHUB_FILE_TOOLS[@]}"
}
# `gh ` at the start of a shell command's string, or after a space, `;`, `&`, `|`, `(` or `/` (or a
# `\n` or `\t` JSON writes): Claude Code's Bash and PowerShell, Copilot's bash, powershell and
# execute, whose toolArgs may hold the input as an escaped JSON string. Builtins only.
GH_WORD='(^|[ ;&|(/]|\\[nt])gh '
shelled() { # <payload>
  [[ $1 == *"gh "* ]] || return 1
  if [[ $1 =~ \"(command|input|script)\"[[:space:]]*:[[:space:]]*\"(([^\"\\]|\\.)*)\" ]] &&
    [[ ${BASH_REMATCH[2]} =~ $GH_WORD ]]; then
    return 0
  fi
  [[ $1 =~ \\\"(command|input|script)\\\"[[:space:]]*:[[:space:]]*\\\"(.*) ]] &&
    [[ ${BASH_REMATCH[2]} =~ $GH_WORD ]]
}
# The gate's answer for the payload: uv where bootstrap.sh installs it, else python3 at 3.11 or
# later; without either it passes and says so in the project's log, as the gate itself does.
gate() { # <payload>
  local script="$here/se_forms.py"
  if PATH="$HOME/.local/bin:$PATH" command -v uv >/dev/null 2>&1; then
    PATH="$HOME/.local/bin:$PATH" uv run --no-project --no-python-downloads --python ">=3.11" \
      python "$script" gate 2>/dev/null <<<"$1"
  elif command -v python3 >/dev/null 2>&1 &&
    python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
    python3 "$script" gate 2>/dev/null <<<"$1"
  elif mkdir -p "$project/.se/.runtime" 2>/dev/null; then
    printf '%s passed unjudged: no Python 3.11 or later (uv or python3)\n' \
      "$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null)" >>"$project/.se/.runtime/forms-gate.log" 2>/dev/null
  fi
}
case "$event" in
Stop | SubagentStop) ;;
*)
  gate_off=false
  case "${SE_FORMS_GATE:-}" in [oO][fF][fF]) gate_off=true ;; esac
  if [ "$event" = PreToolUse ] && ! $gate_off &&
    { guarded "$payload" || shelled "$payload" || filed "$payload"; }; then
    said="$(SE_HOOK_HOST="$se_payload_host" gate "$payload")"
    [ "$se_payload_host" != copilot ] && [ -n "$bin" ] && [ -x "$bin" ] &&
      "$bin" hook "$event" --root "$project" >/dev/null 2>&1 <<<"$payload"
    [ -n "$said" ] && printf '%s\n' "$said"
    exit 0
  fi
  [ "$event" = PreToolUse ] && [ "$se_payload_host" = copilot ] && exit 0
  [ -n "$bin" ] && [ -x "$bin" ] || exit 0
  exec "$bin" hook "$event" --root "$project" 2>/dev/null <<<"$payload"
  ;;
esac
if [ "$se_payload_host" = copilot ] && [[ $payload == *"{"* ]]; then
  rest="${payload#*\{}"
  comma=","
  [[ $rest =~ ^[[:space:]]*\} ]] && comma=""
  payload="${payload%%\{*}{\"${SE_PAYLOAD_HOST[0]}\":\"copilot\"$comma$rest"
fi
# The answer as the host reads it: under Copilot a systemMessage, the check's advice, goes to stderr
# with exit code 2 (above); every other answer is printed as it is.
answer() { # <answer>
  local message='{"systemMessage": "'
  if [ "$se_payload_host" = copilot ] && [[ $1 == "$message"*'"}' ]]; then
    local text="${1#"$message"}"
    text="${text%'"}'}"
    text="${text//\\\"/\"}"
    printf '%b\n' "$text" >&2
    exit 2
  fi
  [ -n "$1" ] && printf '%s\n' "$1"
  exit 0
}
# The fallback's exit code from kern; the wait covers a stop-check that reads GitHub through gh.
unanswered=3
if [ -n "$bin" ] && [ -x "$bin" ]; then
  said="$("$bin" hook "$event" --root "$project" --wait 10s --unanswered "$unanswered" 2>/dev/null <<<"$payload")"
  [ $? -ne "$unanswered" ] && answer "$said"
fi
# uv where bootstrap.sh installs it; --no-project so no project's environment is synced.
check=(uv run --no-project --python ">=3.11" python "$here/work_tickets.py" stop-check)
if [ "$se_payload_host" = copilot ]; then
  answer "$(PATH="$HOME/.local/bin:$PATH" "${check[@]}" <<<"$payload")"
fi
PATH="$HOME/.local/bin:$PATH" exec "${check[@]}" <<<"$payload"
