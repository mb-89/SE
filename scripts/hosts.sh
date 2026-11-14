# shellcheck shell=bash
# The host table: the one place that names how SE tells which host and which cloud runs it, and how
# each host's hook payload names its fields. The hook scripts source it (se_hook.sh, bootstrap.sh);
# scripts/hosts.py reads the same lines as a pure module, environment in, host and cloud out. Each
# table is one line `SE_<NAME>=(<entry> ...)`, so both can read it.
#
# Where the project is, in this order: the first of these variables that is set, then the hook
# payload's cwd, then the working directory. Copilot names no project variable that its docs hold to.
SE_PROJECT_VARIABLES=(CLAUDE_PROJECT_DIR)
# The hosts, each `<host>:<variable>` (set and not empty) or `<host>:<variable>=<value>`: Claude Code
# sets CLAUDECODE in the processes it starts. Only Claude's row: no Copilot variable could be checked
# against a Copilot run yet. A hook file names its host itself instead (SE_HOOK_HOSTS below).
SE_HOST_MARKS=(claude:CLAUDECODE=1 claude:CLAUDE_CODE_REMOTE=true)
# The variable a hook file sets in its hooks' environment to name its host, and the hosts it may name:
# Copilot's .github/hooks/se.json sets SE_HOOK_HOST=copilot (its PascalCase events send Claude-shaped
# payloads, so the payload alone cannot tell). Unset, the host is Claude Code, as on main.
SE_HOOK_HOSTS=(SE_HOOK_HOST claude copilot)
# The clouds, each `<cloud>:<variable>` (set and not empty) or `<cloud>:<variable>=<value>` (that
# value, in any case). `ci` is any GitHub Actions run, not a host.
SE_CLOUD_MARKS=(claude:CLAUDE_CODE_REMOTE=true ci:GITHUB_ACTIONS=true)
# Copilot's camelCase payload fields and the snake_case name Claude Code's payload, kern and
# stop-check read, each `<camelCase>:<snake_case>`. A payload with any of them is Copilot's.
SE_PAYLOAD_KEYS=(sessionId:session_id hookEventName:hook_event_name transcriptPath:transcript_path agentTranscriptPath:agent_transcript_path stopReason:stop_reason stopHookActive:stop_hook_active toolName:tool_name initialPrompt:initial_prompt)

# The hook payload on stdin of the script that sources this, in snake_case whatever host wrote it;
# builtins only, as a hook's cost is kern's own start. Sets se_payload_host to the host the hook file
# names (SE_HOOK_HOST), else `copilot` where it renamed a field, else `claude`.
se_payload() { # <payload>
  local text="$1" pair
  se_payload_host=claude
  for pair in "${SE_PAYLOAD_KEYS[@]}"; do
    if [[ $text == *"\"${pair%%:*}\""* ]]; then
      text="${text//\"${pair%%:*}\"/\"${pair#*:}\"}"
      se_payload_host=copilot
    fi
  done
  [ "${SE_HOOK_HOST:-}" = copilot ] && se_payload_host=copilot
  se_payload_text="$text"
}

# The project of this hook: SE_PROJECT_VARIABLES in order, then the payload's cwd (JSON-unescaped
# backslashes), then the working directory. Sets se_project and se_project_from (variable, cwd, pwd).
se_project() { # <payload>
  local name
  for name in "${SE_PROJECT_VARIABLES[@]}"; do
    if [ -n "${!name:-}" ]; then
      se_project="${!name}"
      se_project_from=variable
      return 0
    fi
  done
  if [[ $1 =~ \"cwd\"[[:space:]]*:[[:space:]]*\"([^\"]*)\" ]] && [ -n "${BASH_REMATCH[1]}" ]; then
    se_project="${BASH_REMATCH[1]//\\\\/\\}"
    se_project_from=cwd
    return 0
  fi
  se_project="$PWD"
  se_project_from=pwd
}
