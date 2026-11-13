#!/usr/bin/env bash
# Bring what se's tools need onto this machine; safe to run again after an interruption.
#
# Run by the Claude Code plugin at every session start and by SE on its first start elsewhere.
# Quiet when nothing is missing. What it does, per dependency, is the README section "Install".
#   git      required; cannot be installed without admin rights, so it names the one line to run
#   uv       installed into the user's home (~/.local/bin) from astral.sh when missing
#   Python   3.11 or newer, installed by uv into the user's home when missing
#   modules  the current project's se.toml modules, synced by se_modules.py
#   kern     in --hook mode: the core SE pins (kern/release.toml), fetched for this platform into
#            ~/.se/bin/kern-<version> in the background (or built from kern/ where no release
#            matches), started detached for the project, and handed the session's start
# Exit code 0 when everything is in place, 1 when a step needs the person: the line on stdout says
# what to run and why (the plugin's hook passes it on to the session).
#
# --hook (the plugin's SessionStart hook): when everything is in place, end with SE's greeting as
# the hook's JSON (scripts/se_start.py status --hook), carrying the lines said on the way and kern's
# state. The hook's JSON on stdin is the session's start, which kern is handed.
set -u

# --kern-fetch and --kern-build: the background half of kern's first start of a version (below).
case "${1:-}" in
  --kern-fetch | --kern-build) kern_mode="$1" ;;
  *) kern_mode="" ;;
esac

hook=false
[ "${1:-}" = "--hook" ] && hook=true
notes=()
kern_args=()
payload=""
if $hook && [ ! -t 0 ]; then payload="$(cat)"; fi

se_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
project="${CLAUDE_PROJECT_DIR:-$PWD}"
uv_url="https://astral.sh/uv/install.sh"
uv_ps_url="https://astral.sh/uv/install.ps1"
python_version="3.11"

say() { notes+=("se bootstrap: $*"); }
# The end: in --hook mode SE's greeting carrying the notes, where uv and Python can run it (R4 of the
# start: the greeting appears even when a step failed); otherwise the notes as plain lines.
finish() {
  if $hook && command -v uv >/dev/null 2>&1; then
    args=()
    for note in ${notes[@]+"${notes[@]}"}; do args+=(--note "$note"); done
    args+=(${kern_args[@]+"${kern_args[@]}"})
    uv run --no-project --python ">=$python_version" python "$se_root/scripts/se_start.py" \
      --root "$project" status --hook ${args[@]+"${args[@]}"} 2>/dev/null && exit "$1"
  fi
  for note in ${notes[@]+"${notes[@]}"}; do printf '%s\n' "$note"; done
  exit "$1"
}
need() {
  say "$*"
  finish 1
}

# kern (README "Kern"): only for a session, in --hook mode.
kern_value() { # the value of `<key> = "..."` in kern/release.toml
  local line value=""
  while IFS= read -r line; do
    case $line in "$1 = \""*) value="${line#"$1" = \"}" && value="${value%%\"*}" ;; esac
  done 2>/dev/null <"$se_root/kern/release.toml"
  printf '%s' "$value"
}
kern_platform() { # <os>-<arch> as kern's release names them, or nothing
  local os arch
  case "$(uname -s 2>/dev/null)" in
    Linux) os=linux ;; Darwin) os=darwin ;; MINGW* | MSYS* | CYGWIN*) os=windows ;; *) return 0 ;;
  esac
  case "$(uname -m 2>/dev/null)" in
    x86_64 | amd64) arch=amd64 ;; aarch64 | arm64) arch=arm64 ;; *) return 0 ;;
  esac
  printf '%s-%s' "$os" "$arch"
}
kern_sha256() { # the SHA-256 of a file
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1"; else shasum -a 256 "$1"; fi | {
    read -r sum _ && printf '%s' "$sum"
  }
}
# Start the core for the project and hand it the session's start; the post waits for the core.
kern_run() { # <bin> <session start file>
  "$1" start --root "$project" >/dev/null 2>"$project/.se/.runtime/kern-start.err" || return 1
  "$1" hook SessionStart --root "$project" <"$2" >/dev/null 2>&1
  return 0
}
# Put the binary in place in the background, from the release or built from kern/, then start it.
# Its own process (setsid where there is one), so the hook's end does not end it.
kern_background() { # <mode> <bin> <args>...
  local detach=()
  command -v setsid >/dev/null 2>&1 && detach=(setsid)
  ${detach[@]+"${detach[@]}"} bash "$se_root/scripts/bootstrap.sh" "$@" </dev/null >/dev/null 2>&1 &
}
kern_step() {
  local version base platform exe=kern asset bin sums cause start
  version="$(kern_value version)"
  base="$(kern_value download)"
  [ -n "$version" ] || return 0
  base="${base//\{version\}/$version}"
  platform="$(kern_platform)"
  case "$platform" in windows-*) exe=kern.exe ;; esac
  bin="$HOME/.se/bin/kern-$version${exe#kern}"
  mkdir -p "$HOME/.se/bin" "$project/.se/.runtime" 2>/dev/null
  start="$project/.se/.runtime/kern-session-start.json"
  printf '%s' "$payload" >"$start"
  if [ -x "$bin" ]; then
    kern_run "$bin" "$start" ||
      kern_args+=(--kern-failed "kern start: $(tail -n 1 "$project/.se/.runtime/kern-start.err" 2>/dev/null)")
    kern_args+=(--kern-bin "$bin")
    return 0
  fi
  # The first start of this version: one small read says whether a release matches this platform.
  asset="kern-$version-$platform.tar.gz"
  [ "$exe" = kern.exe ] && asset="kern-$version-$platform.zip"
  sums="$HOME/.se/bin/kern-$version.SHA256SUMS"
  if [ -z "$platform" ]; then
    cause="no kern release for $(uname -s 2>/dev/null) $(uname -m 2>/dev/null)"
  elif ! command -v curl >/dev/null 2>&1; then
    cause="no curl to fetch release kern-v$version"
  elif ! curl -fsSL --max-time 2 -o "$sums" "$base/SHA256SUMS" >/dev/null 2>&1; then
    cause="no release kern-v$version at $base"
  elif ! grep -q "  $asset\$" "$sums" 2>/dev/null; then
    cause="release kern-v$version has no $asset"
  else
    kern_background --kern-fetch "$bin" "$base/$asset" "$sums" "$exe" "$project" "$start"
    kern_args+=(--kern-starting "fetching release kern-v$version for $platform in the background")
    return 0
  fi
  if command -v go >/dev/null 2>&1 && [ -f "$se_root/kern/go.mod" ]; then
    kern_background --kern-build "$bin" "$project" "$start"
    kern_args+=(--kern-starting "$cause; building it from $se_root/kern in the background")
  else
    kern_args+=(--kern-failed "$cause, and no go to build it from $se_root/kern")
  fi
}
if [ -n "$kern_mode" ]; then
  # <bin> then, for --kern-fetch, <archive url> <SHA256SUMS file> <binary in it>; then the project
  # and the session's start, which the core is handed once it runs.
  bin="$2"
  part="$bin.part$$"
  if [ "$kern_mode" = --kern-fetch ]; then
    project="$6"
    mkdir -p "$part" && curl -fsSL --max-time 120 -o "$part/${3##*/}" "$3" &&
      grep -q "^$(kern_sha256 "$part/${3##*/}")  ${3##*/}\$" "$4" &&
      case "$3" in
        *.zip) (cd "$part" && { unzip -q "${3##*/}" || tar -xf "${3##*/}"; }) ;;
        *) tar -xzf "$part/${3##*/}" -C "$part" ;;
      esac && mv -f "$part/$5" "$bin"
    rm -rf "$part"
    start="$7"
  else
    project="$3"
    (cd "$se_root/kern" && go build -o "$part" ./cmd/kern) && mv -f "$part" "$bin"
    start="$4"
  fi
  [ -x "$bin" ] && kern_run "$bin" "$start"
  exit 0
fi

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
$hook && kern_step
finish 0
