#!/usr/bin/env bash
# Bring what se's tools need onto this machine; safe to run again after an interruption.
#
# Run by the Claude Code plugin at every session start and by SE on its first start elsewhere.
# Quiet when nothing is missing. What it does, per dependency, is the README section "Install".
#   git      required; cannot be installed without admin rights, so it names the one line to run
#   uv       installed into the user's home (~/.local/bin) from astral.sh when missing
#   Python   3.11 or newer, installed by uv into the user's home when missing
#   modules  the current project's se.toml modules, synced by se_modules.py
# Exit code 0 when everything is in place, 1 when a step needs the person: the line on stdout says
# what to run and why (the plugin's hook passes it on to the session).
set -u

se_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
project="${CLAUDE_PROJECT_DIR:-$PWD}"
uv_url="https://astral.sh/uv/install.sh"
uv_ps_url="https://astral.sh/uv/install.ps1"
python_version="3.11"

say() { printf 'se bootstrap: %s\n' "$*"; }
need() { say "$*"; exit 1; }

windows=false
case "$(uname -s 2>/dev/null)" in MINGW* | MSYS* | CYGWIN*) windows=true ;; esac

# git: the one tool that needs the person.
if ! command -v git >/dev/null 2>&1; then
  if $windows; then
    need "git is missing; se's tools run git. Run: winget install --id Git.Git -e"
  elif [ "$(uname -s)" = Darwin ]; then
    need "git is missing; se's tools run git. Run: xcode-select --install"
  else
    need "git is missing; se's tools run git. Run: sudo apt-get install -y git (or your package manager's git)"
  fi
fi

# uv: into the user's home, no admin rights.
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  say "installing uv into $HOME/.local/bin (se's scripts run with it)"
  if $windows; then
    powershell -NoProfile -ExecutionPolicy ByPass -c "irm $uv_ps_url | iex" >/dev/null 2>&1
  elif command -v curl >/dev/null 2>&1; then
    curl -LsSf "$uv_url" | sh >/dev/null 2>&1
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- "$uv_url" | sh >/dev/null 2>&1
  else
    need "uv is missing and neither curl nor wget is here to fetch it. Run: pip install --user uv"
  fi
  command -v uv >/dev/null 2>&1 ||
    need "installing uv failed (offline?). Run this again when online, or install it by hand: curl -LsSf $uv_url | sh"
fi

# Later shells of this Claude Code session find uv too.
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  printf 'export PATH="%s:$PATH"\n' "$(dirname "$(command -v uv)")" >>"$CLAUDE_ENV_FILE"
fi

# Python: uv installs a managed one when none fits.
if ! uv python find ">=$python_version" >/dev/null 2>&1; then
  say "installing Python $python_version with uv (se's scripts need $python_version or newer)"
  uv python install "$python_version" >/dev/null 2>&1 ||
    need "installing Python with uv failed (offline?). Run this again when online: uv python install $python_version"
fi

# Modules: the project's se.toml modules, fetched at their pins.
if [ -f "$project/se.toml" ] && grep -q '^\[modules\.' "$project/se.toml"; then
  if ! out="$(uv run --no-project --python ">=$python_version" python "$se_root/scripts/se_modules.py" --root "$project" sync 2>&1)"; then
    say "$out"
    need "syncing the modules of $project/se.toml failed; run this again when the cause above is fixed"
  fi
fi
exit 0
