# shellcheck shell=bash
# The host table: the one place that names how SE tells which host and which cloud runs it, and how
# each host's hook payload names its fields. Every script reads it instead of checking on its own:
# the shell scripts source it (se_hook.sh, bootstrap.sh), the Python ones read the same lines through
# scripts/hosts.py. Each table is one line `SE_<NAME>=(<entry> ...)`, so both can read it.
#
# Where the project is, in this order: the first of these variables that is set, then the hook
# payload's cwd, then the working directory. Copilot's CLI hooks may lack CLAUDE_PROJECT_DIR.
SE_PROJECT_VARIABLES=(CLAUDE_PROJECT_DIR COPILOT_PROJECT_DIR)
# The clouds, each `<cloud>:<variable>` (set and not empty) or `<cloud>:<variable>=<value>` (that
# value, in any case). `ci` is a GitHub Actions runner, which also runs Copilot's cloud agent; `se`
# marks any other cloud an environment declares to SE.
SE_CLOUD_MARKS=(claude:CLAUDE_CODE_REMOTE=true copilot:COPILOT_AGENT_PROMPT ci:GITHUB_ACTIONS=true se:SE_CLOUD=true)
# Copilot's camelCase payload fields and the snake_case name Claude Code's payload, kern and
# stop-check read, each `<camelCase>:<snake_case>`. A payload with any of them is Copilot's.
SE_PAYLOAD_KEYS=(sessionId:session_id hookEventName:hook_event_name transcriptPath:transcript_path agentTranscriptPath:agent_transcript_path stopReason:stop_reason stopHookActive:stop_hook_active toolName:tool_name initialPrompt:initial_prompt)

# The hook payload on stdin of the script that sources this, in snake_case whatever host wrote it;
# builtins only, as a hook's cost is kern's own start. Sets se_payload_host to `copilot` where it
# renamed a field, else `claude`.
se_payload() { # <payload>
  local text="$1" pair
  se_payload_host=claude
  for pair in "${SE_PAYLOAD_KEYS[@]}"; do
    if [[ $text == *"\"${pair%%:*}\""* ]]; then
      text="${text//\"${pair%%:*}\"/\"${pair#*:}\"}"
      se_payload_host=copilot
    fi
  done
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
