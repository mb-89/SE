#!/bin/sh
# RUNME: installs what RUNME.conf beside it declares and this machine lacks, then runs the tool
# with every argument, in the caller's folder. It owns no option and no help: --help is the tool's.
# This file is the same in every project. RUNME.conf, the project's own, holds one entry a line:
#   path <dir>                  appended to PATH before any check
#   need <name> command <cmd>   present where <cmd> is on PATH (several need lines: any one)
#   need <name> file <path>     present where <path> or <path>.exe exists
#   get <name> <way> <what>     winget <id>, apt|dnf|brew <packages>, or unix|windows|any <command>
#                               run by sh in this folder; tried in order until <name> is present
#   run <command>               the tool, a shell command line; the arguments follow it
# A path starting ~/ is in the home; another relative one is in this folder.
# On Windows RUNME.ps1 installs Git from the line "get git winget <id>"; the name must be git.
set -eu
export RUNME_ROOT="$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)"
conf="$RUNME_ROOT/RUNME.conf"
[ -f "$conf" ] || { echo "RUNME: no RUNME.conf in $RUNME_ROOT" >&2; exit 2; }
at() { case $1 in "~/"*) echo "$HOME/${1#??}" ;; /* | ?:*) echo "$1" ;; *) echo "$RUNME_ROOT/$1" ;; esac; }
case $(uname -s) in
  MINGW* | MSYS* | CYGWIN*) os=windows pm=winget ;; Darwin) os=unix pm=brew ;;
  *) os=unix pm=; if command -v apt-get >/dev/null 2>&1; then pm=apt; elif command -v dnf >/dev/null 2>&1; then pm=dnf; fi ;; esac
sudo=""; [ "$os" = windows ] || [ "$(id -u)" = 0 ] || { sudo="sudo -n "; [ -t 0 ] && sudo="sudo "; }
for dir in $(awk '$1 == "path" { print $2 }' "$conf"); do PATH="$PATH:$(at "$dir")"; done; export PATH
present() { # <name>: one of its need lines holds
  while read -r kind n how what; do
    [ "$kind:$n" = "need:$1" ] || continue
    case $how in command) command -v "$what" >/dev/null 2>&1 && return 0 ;;
      file) f=$(at "$what"); { [ -e "$f" ] || [ -e "$f.exe" ]; } && return 0 ;; esac
  done <"$conf"
  return 1
}
way() { # <way> <what>: the command that installs it on this machine, or nothing
  case $1:$pm in
    winget:winget) echo "winget install --id $2 -e --source winget --accept-package-agreements --accept-source-agreements" ;;
    apt:apt) echo "${sudo}apt-get update -q && ${sudo}apt-get install -y -q $2" ;;
    dnf:dnf) echo "${sudo}dnf install -y $2" ;;
    brew:brew) echo "brew install $2" ;;
    any:* | "$os":*) echo "$2" ;;
  esac
}
refresh() { # on Windows, the PATH an installer left for the next terminal, in this one
  [ "$os" = windows ] || return 0
  PATH="$PATH:$(cygpath -p "$(powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('Path','Machine')+';'+[Environment]::GetEnvironmentVariable('Path','User')" </dev/null | tr -d '\r')")"
}
for name in $(awk '$1 == "need" && !seen[$2]++ { print $2 }' "$conf"); do
  present "$name" && continue
  first=""
  while read -r kind n w what; do
    [ "$kind:$n" = "get:$name" ] && cmd=$(way "$w" "$what") && [ -n "$cmd" ] || continue
    first=${first:-$(printf '%s' "$cmd" | sed 's/sudo -n /sudo /g')}
    echo "RUNME: installing $name: $cmd" >&2
    (cd "$RUNME_ROOT" && sh -c "$cmd") </dev/null >&2 && refresh && present "$name" && break
  done <"$conf"
  present "$name" && continue
  echo "RUNME: $name is missing; run: ${first:-what installs it here (RUNME.conf names no way)}" >&2
  exit 1
done
run=$(sed -n 's/^run[[:space:]][[:space:]]*//p' "$conf")
[ -n "$run" ] || { echo "RUNME: RUNME.conf has no run line" >&2; exit 2; }
eval "exec $run \"\$@\""
