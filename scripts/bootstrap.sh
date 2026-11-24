#!/usr/bin/env bash
# Bring what se's tools need onto this machine; safe to run again after an interruption.
#
# Run at every session start by the Claude Code plugin and by Copilot's hooks (.github/hooks/se.json),
# by SE on its first start elsewhere, and with --binary by RUNME (RUNME.conf), which places `se` once.
# Quiet when nothing is missing. What it does, per dependency, is the README section "Install".
#   git      required; cannot be installed without admin rights, so it names the one line to run
#   uv       installed into the user's home (~/.local/bin) from astral.sh when missing
#   Python   3.11 or newer, installed by uv into the user's home when missing
#   modules  the current project's se.toml components and theirs, resolved from what is placed first
#            (se_start.py start-components); a required one missing stops the start
#   identity in --hook mode: the project's commit identity, set as setup.sh sets it
#   hooks    in --hook mode: the project's core.hooksPath where it is unset, set as setup.sh sets it
#   SE       in --hook mode: an installed SE that is a git checkout behind SE's latest release within
#            its major is moved to it first (se_start.py start-refresh), and the start then runs again
#            from the moved tree, so the core starts from its pins; a refresh that fails starts with
#            the SE in place and says so in one line
#   kern     in --hook mode, for a project inside a git checkout: the application binary
#            (se_modules.py app-binary) — kern's core plus the application's Go components where it
#            has any (the `se` binary for SE), else the bare kern — fetched for this platform into ~/.se/bin/<name>-<version> in the background (or built
#            from its folder where no release matches, on the installed SE's kern, placed first at
#            the pin its se.toml [components.kern] reads: kern_place), started detached for the project, and handed
#            the session's start; SE_HOOK_CORE=off, or [hooks] core = "off" in ~/.se/local.toml,
#            skips this step (below)
# --binary (RUNME.conf's `get se` line, run by SE's RUNME): the plain run's git, uv and Python steps,
# then the binary SE's own checkout pins, fetched from its release in the foreground (built with go
# where none matches), linked as ~/.se/bin/<name>, and its version written to
# <se root>/.se/.runtime/runme-se, RUNME's need; it syncs no module, sets no identity or hooks,
# writes no kern.path and starts nothing.
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
binary=false
[ "${1:-}" = "--binary" ] && binary=true
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
# Once per session under Copilot, which runs every hook source it finds together (a project's and a
# plugin's): a second start of the same session within a minute ends here, quietly. Claude Code
# starts a session again after every compaction (the payload's source "compact"); that start is not
# ended here, as the session keeps <se> and its greeting only from a start's context, but it skips
# the steps that already ran (see compact below).
if $hook && [ "$se_payload_host" = copilot ] &&
  [[ $payload =~ \"session_id\"[[:space:]]*:[[:space:]]*\"([^\"/\\]+)\" ]]; then
  claim="$project/.se/.runtime/start-${BASH_REMATCH[1]}.claim"
  mkdir -p "$project/.se/.runtime" 2>/dev/null
  if [ -e "$claim" ] && [ -n "$(find "$claim" -mmin -1 2>/dev/null)" ]; then
    exit 0
  fi
  rm -f "$claim"
  (set -C && : >"$claim") 2>/dev/null || exit 0
fi
# A start after a compaction (Claude Code's payload source "compact") runs no release refresh, module
# sync, commit identity or hooks again: they ran at the session's own start. Every other source
# (startup, resume, clear, or none) runs every step.
compact=false
if $hook && [[ $payload =~ \"source\"[[:space:]]*:[[:space:]]*\"compact\" ]]; then compact=true; fi
uv_url="https://astral.sh/uv/install.sh"
uv_ps_url="https://astral.sh/uv/install.ps1"
python_version="3.11"

say() { notes+=("se bootstrap: $*"); }
# The end: in --hook mode SE's greeting carrying the notes, where uv and Python can run it (R4 of the
# start: the greeting appears even when a step failed); otherwise the notes as plain lines.
finish() {
  if $hook && command -v uv >/dev/null 2>&1; then
    args=()
    [ "$se_payload_host" = copilot ] && args+=(--host copilot)
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
# Start the core for its checkout (kern_root: the project, or SE's root where the project is inside
# no git checkout) and hand it the session's start; the post waits for the core.
# `--home`: a project that keeps no wiring of its own is served SE's (kern's cli.Source), as the MCP
# door's launcher (se_mcp.sh) serves it.
kern_run() { # <bin> <session start file>
  kern_link "$1"
  "$1" start --root "$kern_root" --home "$se_root" >/dev/null 2>"$kern_root/.se/.runtime/kern-start.err" || return 1
  "$1" hook SessionStart --root "$kern_root" <"$2" >/dev/null 2>&1
  return 0
}
# Put the binary in place in the background, from the release or built from its folder, then start it.
# Its own process (setsid where there is one), so the hook's end does not end it.
# kern is required (docs/boot.md "Required components"): the start waits for that background up to
# SE_KERN_WAIT seconds (45 by default), within the host's hook budget; one that runs longer goes on,
# and this start stops naming kern.
kern_background() { # <mode> <bin> <args>...
  local detach=() pid waited=0
  command -v setsid >/dev/null 2>&1 && detach=(setsid)
  ${detach[@]+"${detach[@]}"} bash "$se_root/scripts/bootstrap.sh" "$@" </dev/null >/dev/null 2>&1 &
  pid=$!
  while kill -0 "$pid" 2>/dev/null && [ "$waited" -lt "${SE_KERN_WAIT:-45}" ]; do
    sleep 1
    waited=$((waited + 1))
  done
}
# Whether the project is inside a git checkout: it or a folder above it holds a .git, the folder or
# the file a linked worktree has; the same walk up as the late checkout's in scripts/se_hook.sh.
kern_checkout() {
  local dir="$project" up
  while [ -n "$dir" ]; do
    [ -e "$dir/.git" ] && return 0
    up="${dir%[/\\]*}"
    [ "$up" = "$dir" ] && return 1
    dir="$up"
  done
  return 1
}
# The application binary this start places (README "Kern"): one reader, se_modules.py app-binary,
# which answers kern's core plus the application's Go components where it has any, else the bare
# kern (SE's docs/go-core.md "How the binary arrives"), from the project where it is SE's own
# checkout. One line: "<name> <version> <download base> <build folder> <package> <the checkout it
# read>". The download base lies under the home the checkout's origin names (scripts/se_home.py), so
# no file names where SE lives; it is `-` where origin names none, and the binary is built from its
# folder. Sets name, version, base, builddir, package, pins, platform, exe, suffix and bin; fails
# where there is none.
kern_locate() {
  local spec
  spec="$(uv run --no-project --python ">=$python_version" python "$se_root/scripts/se_modules.py" \
    --root "$se_root" app-binary --project "$project" 2>/dev/null)" || return 1
  read -r name version base builddir package pins <<<"$spec"
  [ -n "$pins" ] || pins="$se_root"
  [ -n "$name" ] && [ -n "$version" ] && [ -n "$base" ] && [ -n "$builddir" ] && [ -n "$package" ] || return 1
  platform="$(kern_platform)"
  exe="$name"
  suffix=""
  case "$platform" in windows-*) exe="$name.exe"; suffix=".exe" ;; esac
  bin="$HOME/.se/bin/$name-$version$suffix"
  mkdir -p "$HOME/.se/bin" 2>/dev/null
}
# Whether a release of the binary matches this platform: one small read. Sets asset and sums, and
# cause to why none does (empty where one does).
kern_release() {
  asset="$name-$version-$platform.tar.gz"
  [ -n "$suffix" ] && asset="$name-$version-$platform.zip"
  sums="$HOME/.se/bin/$name-$version.SHA256SUMS"
  cause=""
  if [ "$base" = - ]; then
    cause="no $name $version release to fetch: the origin of $pins names no home"
  elif [ -z "$platform" ]; then
    cause="no $name release for $(uname -s 2>/dev/null) $(uname -m 2>/dev/null)"
  elif ! command -v curl >/dev/null 2>&1; then
    cause="no curl to fetch the $name $version release"
  elif ! curl -fsSL --max-time 2 -o "$sums" "$base/SHA256SUMS" >/dev/null 2>&1; then
    cause="no $name $version release at $base"
  elif ! grep -q "  $asset\$" "$sums" 2>/dev/null; then
    cause="the $name $version release has no $asset"
  fi
}
# Fetch the release archive, check it against SHA256SUMS and put its binary at <bin>.
kern_fetch() { # <bin> <archive url> <SHA256SUMS file> <binary in it>
  local part="$1.part$$" ok=1
  mkdir -p "$part" && curl -fsSL --max-time 120 -o "$part/${2##*/}" "$2" &&
    grep -q "^$(kern_sha256 "$part/${2##*/}")  ${2##*/}\$" "$3" &&
    case "$2" in
      *.zip) (cd "$part" && { unzip -q "${2##*/}" || tar -xf "${2##*/}"; }) ;;
      *) tar -xzf "$part/${2##*/}" -C "$part" ;;
    esac && mv -f "$part/$4" "$1" && ok=0
  rm -rf "$part"
  return "$ok"
}
# Build the binary with go from its folder into <bin>; its go.mod replaces kern by the clone
# kern_place put in place.
kern_build() { # <bin> <build folder> <package>
  local part="$1.part$$"
  (cd "$2" && go build -o "$part" "$3") && mv -f "$part" "$1"
}
# kern for the installed SE (its se.toml [components.kern], README "Modules"), which a build of its
# binary builds on: synced where its clone in .se/modules/kern is missing or not at the commit
# se.lock locks, both read from the files alone, so an SE at its pin starts no process here. Where
# that fails, the start goes on without it and the greeting names the cause. A project that is SE's
# own checkout syncs it in the modules step.
kern_place() {
  [ -f "$se_root/se.toml" ] && grep -q '^\[components\.kern\]' "$se_root/se.toml" || return 0
  local locked="" head="" inside=false line out
  if [ -f "$se_root/se.lock" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
      line="${line%$'\r'}"
      case "$line" in
        "[components.kern]") inside=true ;;
        "["*) inside=false ;;
        "ref = \""*) $inside && { locked="${line#ref = \"}"; locked="${locked%\"}"; } ;;
      esac
    done <"$se_root/se.lock"
  fi
  [ -f "$se_root/.se/modules/kern/.git/HEAD" ] && IFS= read -r head <"$se_root/.se/modules/kern/.git/HEAD"
  [ -n "$locked" ] && [ "${head%$'\r'}" = "$locked" ] && return 0
  if ! out="$(uv run --no-project --python ">=$python_version" python "$se_root/scripts/se_modules.py" \
      --root "$se_root" sync kern 2>&1)"; then
    notes+=("SE: placing kern for $se_root failed, so this start goes on without it: ${out##*$'\n'}")
  fi
}
kern_step() {
  local start doing
  # kern is one of SE's required components (docs/boot.md "Required components"): it starts at every
  # session's start. For a project inside no git checkout, as a session started without sources
  # is (README "Cloud sessions"), it starts for SE's root; the later hooks find no binary named for
  # the project and fail open, and a late checkout's first hook starts that checkout's core
  # (scripts/se_hook.sh). The session's shells find it as `se`.
  kern_root="$project"
  kern_checkout || kern_root="$se_root"
  [ "$project" -ef "$se_root" ] || kern_place
  if ! kern_locate; then
    kern_args+=(--kern-failed "SE names no application binary for $kern_root (se_modules.py app-binary)")
    return 0
  fi
  mkdir -p "$kern_root/.se/.runtime" 2>/dev/null
  # Where every later hook finds the binary (scripts/se_hook.sh), once it is in place; the
  # session's shells find it as `se` (kern_link).
  printf '%s\n' "$bin" >"$kern_root/.se/.runtime/kern.path"
  [ -n "${CLAUDE_ENV_FILE:-}" ] && printf 'export PATH="%s:$PATH"\n' "$HOME/.se/bin" >>"$CLAUDE_ENV_FILE"
  start="$kern_root/.se/.runtime/kern-session-start.json"
  printf '%s' "$payload" >"$start"
  if [ -x "$bin" ]; then
    kern_run "$bin" "$start" ||
      kern_args+=(--kern-failed "$name start: $(tail -n 1 "$kern_root/.se/.runtime/kern-start.err" 2>/dev/null)")
    kern_args+=(--kern-bin "$bin")
    return 0
  fi
  # The first start of this version: fetched where a release matches this platform, else built, in
  # a background of its own that this start waits for (kern_background).
  kern_release
  if [ -z "$cause" ]; then
    doing="fetching the $name $version release for $platform"
    kern_background --kern-fetch "$bin" "$base/$asset" "$sums" "$exe" "$kern_root" "$start"
  elif command -v go >/dev/null 2>&1 && [ -f "$pins/$builddir/go.mod" ]; then
    doing="$cause; building it from $pins/$builddir"
    kern_background --kern-build "$bin" "$kern_root" "$start" "$pins/$builddir" "$package"
  else
    kern_args+=(--kern-failed "$cause, and no go to build it from $pins/$builddir")
    return 0
  fi
  if [ -x "$bin" ]; then
    kern_args+=(--kern-bin "$bin")
  else
    kern_args+=(--kern-failed "$doing took longer than ${SE_KERN_WAIT:-45} s and goes on in the background; start the session again once $bin is in place")
  fi
}
# --binary: the binary SE's own checkout pins, placed in the foreground and started never (RUNME's
# `get se` line): fetched from its release, else built with go, then linked as ~/.se/bin/<name>;
# its last step writes <se root>/.se/.runtime/runme-se, the version it linked, RUNME's need.
binary_step() {
  project="$se_root"
  kern_place
  kern_locate || need "SE's checkout $se_root names no application binary (se_modules.py app-binary)"
  if [ ! -x "$bin" ]; then
    kern_release
    if [ -z "$cause" ]; then
      kern_fetch "$bin" "$base/$asset" "$sums" "$exe" || cause="fetching $base/$asset failed"
    fi
    if [ -n "$cause" ] && [ ! -x "$bin" ]; then
      if command -v go >/dev/null 2>&1 && [ -f "$pins/$builddir/go.mod" ]; then
        kern_build "$bin" "$pins/$builddir" "$package" ||
          need "$cause, and building it from $pins/$builddir with go failed"
      else
        need "$cause, and no go to build it from $pins/$builddir"
      fi
    fi
  fi
  kern_link "$bin"
  mkdir -p "$se_root/.se/.runtime" && printf '%s\n' "$version" >"$se_root/.se/.runtime/runme-se"
}
if [ -n "$kern_mode" ]; then
  # <bin> then, for --kern-fetch, <archive url> <SHA256SUMS file> <binary in it> <project> <start>;
  # for --kern-build, <project> <start> <build folder> <package>. The core is handed <start> once
  # it runs.
  bin="$2"
  if [ "$kern_mode" = --kern-fetch ]; then
    kern_root="$6"
    kern_fetch "$bin" "$3" "$4" "$5"
    start="$7"
  else
    kern_root="$3"
    kern_build "$bin" "$5" "$6"
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
if $hook && ! $compact && [ -z "${SE_START_REFRESHED:-}" ]; then
  if line="$(uv run --no-project --python ">=$python_version" python "$se_root/scripts/se_start.py" \
    --root "$project" start-refresh 2>/dev/null)"; then
    carried=""
    for note in ${notes[@]+"${notes[@]}"}; do carried+="$note"$'\n'; done
    SE_START_REFRESHED="$carried$line" exec bash "$se_root/scripts/bootstrap.sh" --hook <<<"$payload"
  fi
  [ -n "$line" ] && notes+=("$line")
fi

# --binary (RUNME): the binary, placed and linked; no module, identity, hooks or core.
if $binary; then
  binary_step
  finish 0
fi

# Components (docs/components.md "Required and optional at start"): the tree of the project's
# se.toml [components] resolved before the core starts, from what is placed first, the rest found
# and placed at its pins (se_start.py start-components). Its lines are shown as they are: an
# optional component missing is one line and the start goes on; a required one missing stops the
# start here, its message the greeting's, and nothing after it runs (no identity, hooks or core).
if ! $compact && [ -f "$project/se.toml" ] && grep -q '^\[components\.' "$project/se.toml"; then
  out="$(uv run --no-project --python ">=$python_version" python "$se_root/scripts/se_start.py" \
    --root "$project" start-components 2>/dev/null)"
  stopped=$?
  while IFS= read -r line; do [ -n "$line" ] && notes+=("$line"); done <<<"$out"
  if [ "$stopped" != 0 ]; then
    [ -n "$out" ] && finish 1
    need "SE cannot start: checking the components of $project/se.toml failed; run: uv run python $se_root/scripts/se_start.py --root $project start-components"
  fi
fi
# The commit identity (README "Install"): at a session's start the project's checkout gets its
# commit identity as setup.sh sets it, so a fresh clone's first commit already carries it, never the
# host's default; work_tickets.py identity owns which one, and leaves git's own where none is set.
if $hook && ! $compact && [ -f "$project/se.toml" ]; then
  uv run --no-project --python ">=$python_version" python "$se_root/scripts/work_tickets.py" \
    identity --worktree "$project" >/dev/null 2>&1 ||
    say "setting the commit identity of $project failed; run: uv run python $se_root/scripts/work_tickets.py identity --worktree $project"
fi
# The hooks (AGENTS.md "Public safety"): a checkout whose core.hooksPath is unset gets se's hooks
# at start, as setup.sh sets them, so a fresh clone's first commit already runs the public check; a
# checkout that has one keeps it (se_start.py start-hooks owns which hooks).
if $hook && ! $compact && [ -f "$project/se.toml" ]; then
  line="$(uv run --no-project --python ">=$python_version" python "$se_root/scripts/se_start.py" \
    --root "$project" start-hooks 2>/dev/null)"
  [ -n "$line" ] && notes+=("$line")
fi
# The file gate's line (README "Templates"): where a template claims a path, the line claimed in
# <project>/.se/.runtime/templates-files, as kern.path is written, so se_hook.sh guards the file
# tools with builtins alone; removed otherwise. A template added during a session is guarded from
# the next session's start.
if $hook && ! $compact; then
  if [ -f "$project/se.toml" ]; then
    uv run --no-project --python ">=$python_version" python "$se_root/scripts/se_templates.py" gate \
      --runtime "$project" >/dev/null 2>&1 || rm -f "$project/.se/.runtime/templates-files"
  else
    rm -f "$project/.se/.runtime/templates-files"
  fi
fi
# The core switch (README "Machine-local `~/.se/local.toml`"): SE_HOOK_CORE in the environment
# answers first wherever it is set, else [hooks] core of the machine's local file, read through
# se_modules.py hooks-core only where that file mentions hooks, so a machine without the setting
# starts no new process. Off, this start runs no kern step and leaves no kern.path, so the later
# hooks (scripts/se_hook.sh) answer without a core; a core already running is not stopped.
hook_core=""
if $hook; then
  if [ -n "${SE_HOOK_CORE+set}" ]; then
    case "$SE_HOOK_CORE" in [oO][fF][fF]) hook_core="SE_HOOK_CORE is off in the environment" ;; esac
  elif [ -f "$HOME/.se/local.toml" ] && grep -q hooks "$HOME/.se/local.toml" 2>/dev/null; then
    answer="$(uv run --no-project --python ">=$python_version" python "$se_root/scripts/se_modules.py" \
      --local "$HOME/.se/local.toml" hooks-core 2>/dev/null)"
    [ "${answer%$'\r'}" = "off local" ] && hook_core="[hooks] core is off in ~/.se/local.toml"
  fi
fi
if [ -n "$hook_core" ]; then
  rm -f "$project/.se/.runtime/kern.path"
  notes+=("SE: no core at this start: $hook_core; the hooks answer without one")
  kern_args+=(--kern-off "$hook_core")
elif $hook; then
  kern_step
fi
finish 0
