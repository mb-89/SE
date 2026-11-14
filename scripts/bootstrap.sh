#!/usr/bin/env bash
# Bring what se's tools need onto this machine; safe to run again after an interruption.
#
# Run at every session start by the Claude Code plugin and by Copilot's hooks (.github/hooks/se.json),
# and by SE on its first start elsewhere.
# Quiet when nothing is missing. What it does, per dependency, is the README section "Install".
#   git      required; cannot be installed without admin rights, so it names the one line to run
#   uv       installed into the user's home (~/.local/bin) from astral.sh when missing
#   Python   3.11 or newer, installed by uv into the user's home when missing
#   modules  the current project's se.toml modules, synced by se_modules.py
#   identity in --hook mode: the project's commit identity, set as setup.sh sets it
#   SE       in --hook mode: an installed SE that is a git checkout behind SE's latest release within
#            its major is moved to it first (se_start.py start-refresh), and the start then runs again
#            from the moved tree, so the core starts from its pins; a refresh that fails starts with
#            the SE in place and says so in one line
#   kern     in --hook mode: the application binary (se_modules.py app-binary) — kern's core plus the
#            application's Go components where it has any (the `se` binary for SE), else the bare kern
#            — fetched for this platform into ~/.se/bin/<name>-<version> in the background (or built
#            from its folder where no release matches), started detached for the project, and handed
#            the session's start
# Exit code 0 when everything is in place, 1 when a step needs the person: the line on stdout says
# what to run and why (the plugin's hook passes it on to the session).
#
# --hook (the SessionStart hook of Claude Code's plugin and of Copilot's .github/hooks/se.json): when
# everything is in place, end with SE's greeting as the hook's JSON for the host that wrote the
# payload (scripts/se_start.py status --hook --host), carrying the lines said on the way and kern's
# state. The hook's JSON on stdin is the session's start, which kern is handed.
set -u
# uv's deprecated UV_NATIVE_TLS, which cloud environments set, becomes UV_SYSTEM_CERTS for all this
# runs, the core and the components it places with `uv run` among them: core.log stays free of
# uv's deprecation notice (as scripts/build_docs.py does for the docs build).
if [ -n "${UV_NATIVE_TLS:-}" ]; then
  export UV_SYSTEM_CERTS="${UV_SYSTEM_CERTS:-$UV_NATIVE_TLS}"
  unset UV_NATIVE_TLS
fi

# --kern-fetch and --kern-build: the background half of kern's first start of a version (below).
case "${1:-}" in
  --kern-fetch | --kern-build) kern_mode="$1" ;;
  *) kern_mode="" ;;
esac

hook=false
[ "${1:-}" = "--hook" ] && hook=true
notes=()
# The lines the start before a refresh said (se_start.py start-refresh), carried into this one.
if [ -n "${SE_START_REFRESHED:-}" ]; then
  while IFS= read -r line; do [ -n "$line" ] && notes+=("$line"); done <<<"$SE_START_REFRESHED"
fi
kern_args=()
payload=""
if $hook && [ ! -t 0 ]; then payload="$(cat)"; fi

se_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Either host (scripts/hosts.sh, the host table): the start's payload in snake_case, whichever host
# wrote it, and the project from the host's project variable, else the payload's cwd, else here.
# shellcheck source=hosts.sh
. "$se_root/scripts/hosts.sh"
se_payload "$payload"
payload="$se_payload_text"
se_project "$payload"
project="$se_project"
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
      --root "$project" status --hook --host "$se_payload_host" ${args[@]+"${args[@]}"} 2>/dev/null &&
      exit "$1"
  fi
  for note in ${notes[@]+"${notes[@]}"}; do printf '%s\n' "$note"; done
  exit "$1"
}
need() {
  say "$*"
  finish 1
}

# kern (README "Kern"): only for a session, in --hook mode.
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
# ~/.se/bin/<name> names the version in place, so `se status` works from the session's PATH: a
# link where the file system makes one, else a copy.
kern_link() { # <bin>
  local dir="${1%/*}" base="${1##*/}" ext=""
  case "$base" in *.exe) ext=".exe" ;; esac
  ln -sf "$base" "$dir/${base%%-[0-9]*}$ext" 2>/dev/null || cp -f "$1" "$dir/${base%%-[0-9]*}$ext"
}
# Start the core for the project and hand it the session's start; the post waits for the core.
kern_run() { # <bin> <session start file>
  kern_link "$1"
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
  local spec name version base builddir package platform exe suffix asset bin sums cause start
  local pins
  # One reader of the application binary: se_modules.py app-binary, which answers kern's core plus
  # the application's Go components where it has any, else the bare kern (SE's docs/go-core.md "How
  # the binary arrives"), from the project where it is SE's own checkout. One line: "<name>
  # <version> <download base> <build folder> <package> <the checkout it read>".
  spec="$(uv run --no-project --python ">=$python_version" python "$se_root/scripts/se_modules.py" \
    --root "$se_root" app-binary --project "$project" 2>/dev/null)" || return 0
  read -r name version base builddir package pins <<<"$spec"
  [ -n "$pins" ] || pins="$se_root"
  [ -n "$name" ] && [ -n "$version" ] && [ -n "$base" ] && [ -n "$builddir" ] && [ -n "$package" ] || return 0
  platform="$(kern_platform)"
  exe="$name"
  suffix=""
  case "$platform" in windows-*) exe="$name.exe"; suffix=".exe" ;; esac
  bin="$HOME/.se/bin/$name-$version$suffix"
  mkdir -p "$HOME/.se/bin" "$project/.se/.runtime" 2>/dev/null
  # Where every later hook finds the binary (scripts/se_hook.sh), once it is in place; the
  # session's shells find it as `se` (kern_link).
  printf '%s\n' "$bin" >"$project/.se/.runtime/kern.path"
  [ -n "${CLAUDE_ENV_FILE:-}" ] && printf 'export PATH="%s:$PATH"\n' "$HOME/.se/bin" >>"$CLAUDE_ENV_FILE"
  start="$project/.se/.runtime/kern-session-start.json"
  printf '%s' "$payload" >"$start"
  if [ -x "$bin" ]; then
    kern_run "$bin" "$start" ||
      kern_args+=(--kern-failed "$name start: $(tail -n 1 "$project/.se/.runtime/kern-start.err" 2>/dev/null)")
    kern_args+=(--kern-bin "$bin")
    return 0
  fi
  # The first start of this version: one small read says whether a release matches this platform.
  asset="$name-$version-$platform.tar.gz"
  [ -n "$suffix" ] && asset="$name-$version-$platform.zip"
  sums="$HOME/.se/bin/$name-$version.SHA256SUMS"
  if [ -z "$platform" ]; then
    cause="no $name release for $(uname -s 2>/dev/null) $(uname -m 2>/dev/null)"
  elif ! command -v curl >/dev/null 2>&1; then
    cause="no curl to fetch the $name $version release"
  elif ! curl -fsSL --max-time 2 -o "$sums" "$base/SHA256SUMS" >/dev/null 2>&1; then
    cause="no $name $version release at $base"
  elif ! grep -q "  $asset\$" "$sums" 2>/dev/null; then
    cause="the $name $version release has no $asset"
  else
    kern_background --kern-fetch "$bin" "$base/$asset" "$sums" "$exe" "$project" "$start"
    kern_args+=(--kern-starting "fetching the $name $version release for $platform in the background")
    return 0
  fi
  if command -v go >/dev/null 2>&1 && [ -f "$pins/$builddir/go.mod" ]; then
    kern_background --kern-build "$bin" "$project" "$start" "$pins/$builddir" "$package"
    kern_args+=(--kern-starting "$cause; building it from $pins/$builddir in the background")
  else
    kern_args+=(--kern-failed "$cause, and no go to build it from $pins/$builddir")
  fi
}
if [ -n "$kern_mode" ]; then
  # <bin> then, for --kern-fetch, <archive url> <SHA256SUMS file> <binary in it> <project> <start>;
  # for --kern-build, <project> <start> <build folder> <package>. The core is handed <start> once
  # it runs.
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
    (cd "${5:-$se_root/kern}" && go build -o "$part" "${6:-./cmd/kern}") && mv -f "$part" "$bin"
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

# SE itself (README "Start and refresh"): where the installed SE moved to a newer release, the start
# runs again from the moved tree, once, carrying what this one said. It fails open: a refresh that
# cannot reach the remote or fails says so in one line and the start goes on with the SE in place.
if $hook && [ -z "${SE_START_REFRESHED:-}" ]; then
  if line="$(uv run --no-project --python ">=$python_version" python "$se_root/scripts/se_start.py" \
    --root "$project" start-refresh 2>/dev/null)"; then
    carried=""
    for note in ${notes[@]+"${notes[@]}"}; do carried+="$note"$'\n'; done
    SE_START_REFRESHED="$carried$line" exec bash "$se_root/scripts/bootstrap.sh" --hook <<<"$payload"
  fi
  [ -n "$line" ] && notes+=("$line")
fi

# Modules: the project's se.toml modules, fetched at their pins.
if [ -f "$project/se.toml" ] && grep -q '^\[modules\.' "$project/se.toml"; then
  if ! out="$(uv run --no-project --python ">=$python_version" python "$se_root/scripts/se_modules.py" --root "$project" sync 2>&1)"; then
    say "$out"
    need "syncing the modules of $project/se.toml failed; run this again when the cause above is fixed"
  fi
fi
# The commit identity (README "Install"): at a session's start the project's checkout gets its
# commit identity as setup.sh sets it, so a fresh clone's first commit already carries it, never the
# host's default; work_tickets.py identity owns which one, and leaves git's own where none is set.
if $hook && [ -f "$project/se.toml" ]; then
  uv run --no-project --python ">=$python_version" python "$se_root/scripts/work_tickets.py" \
    identity --worktree "$project" >/dev/null 2>&1 ||
    say "setting the commit identity of $project failed; run: uv run python $se_root/scripts/work_tickets.py identity --worktree $project"
fi
$hook && kern_step
finish 0
