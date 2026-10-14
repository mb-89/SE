#!/bin/sh
# Every tool SE needs, pinned: one place for their versions. RUNME.sh, CI and
# tests/check.sh run `sh tests/tools.sh install`, which installs whichever is
# missing into $SE_HOME (~/.se) without admin rights: each from its release
# archive for this platform, checked against the checksum its release
# publishes, and claude by Anthropic's native installer. check.sh sources this
# file and refuses linters at any other version, so every machine lints alike.
# The formatters are the linters' own (golangci-lint fmt, biome format).
GH=2.89.0
GO=1.24.7
DLV=1.25.2
GOLANGCI_LINT=2.5.0
BIOME=2.2.4
# Biome's releases publish no checksums, so its binaries' are pinned here.
BIOME_SHA256="
2dde21485b99516d12f031f46b2654dbbf3591c16a40b89ae2562af5b882c3c4  biome-linux-x64
249ebcd10a020969088378b1d3c1df586208e5707230d550197ea20185fac3f3  biome-linux-arm64
23f11ca725182003a9df737b836d568bc2f289e15852fd10d0d076f5354fa2db  biome-darwin-x64
c6bf6a9b550bb0e06b79f0d82d50d24e1cc20388db6d7cdf4893e320945918fc  biome-darwin-arm64
7eaa28a3782192b7c443fc50ead097a56e4edbc669b5963f2c2cab3eaabbd94e  biome-win32-x64.exe
85d834055d8429728513023cfb63f327b5e5eeceebe59befd4f7c736d8af5924  biome-win32-arm64.exe
"

SE_HOME=${SE_HOME:-$HOME/.se}
# The folders the install fills, and the line that puts them on the PATH.
tools_path() {
  echo "$SE_HOME/bin:$SE_HOME/go/bin:$HOME/.local/bin"
}
PATH="$(tools_path):$PATH"
# Tools installed with go install before SE kept its own folder.
if gopath=$(go env GOPATH 2>/dev/null) && [ -n "$gopath" ]; then
  command -v cygpath >/dev/null 2>&1 && gopath=$(cygpath -u "$gopath")
  PATH="$PATH:$gopath/bin"
fi

# tools_platform names the os (linux, darwin or windows) and the arch (amd64 or
# arm64) for `uname -s` and `uname -m`; MINGW* and MSYS* are Git Bash on Windows.
tools_platform() {
  case $1 in
    Linux) os=linux ;;
    Darwin) os=darwin ;;
    MINGW* | MSYS* | CYGWIN*) os=windows ;;
    *) echo "tools: no release for the system $1" >&2; return 1 ;;
  esac
  case $2 in
    x86_64 | amd64) arch=amd64 ;;
    aarch64 | arm64) arch=arm64 ;;
    *) echo "tools: no release for the machine $2" >&2; return 1 ;;
  esac
  echo "$os $arch"
}

# tools_asset names the release file of tool for `uname -s` and `uname -m`.
tools_asset() {
  platform=$(tools_platform "$2" "$3") || return 1
  set -- "$1" $platform
  zip=tar.gz
  [ "$2" = windows ] && zip=zip
  case $1 in
    gh)
      ghos=$2
      [ "$2" = darwin ] && { ghos=macOS; zip=zip; }
      echo "gh_${GH}_${ghos}_$3.$zip"
      ;;
    go) echo "go$GO.$2-$3.$zip" ;;
    golangci-lint) echo "golangci-lint-$GOLANGCI_LINT-$2-$3.$zip" ;;
    biome)
      bos=$2 barch=x64 exe=
      [ "$2" = windows ] && { bos=win32; exe=.exe; }
      [ "$3" = arm64 ] && barch=arm64
      echo "biome-$bos-$barch$exe"
      ;;
  esac
}

# tools_url is where tool's release file, and its checksums, are published.
tools_url() {
  case $1 in
    gh) echo "https://github.com/cli/cli/releases/download/v$GH/$2 https://github.com/cli/cli/releases/download/v$GH/gh_${GH}_checksums.txt" ;;
    go) echo "https://dl.google.com/go/$2 https://dl.google.com/go/$2.sha256" ;;
    golangci-lint) echo "https://github.com/golangci/golangci-lint/releases/download/v$GOLANGCI_LINT/$2 https://github.com/golangci/golangci-lint/releases/download/v$GOLANGCI_LINT/golangci-lint-$GOLANGCI_LINT-checksums.txt" ;;
    biome) echo "https://github.com/biomejs/biome/releases/download/%40biomejs%2Fbiome%40$BIOME/$2 -" ;;
  esac
}

# tools_exe is the name of a binary on `uname -s`.
tools_exe() {
  case $2 in
    MINGW* | MSYS* | CYGWIN*) echo "$1.exe" ;;
    *) echo "$1" ;;
  esac
}

# tools_differ names each tool that is missing, and each pinned linter that is
# at another version.
tools_differ() {
  command -v go >/dev/null 2>&1 || echo "go $GO"
  command -v gh >/dev/null 2>&1 || echo "gh $GH"
  golangci-lint --version 2>/dev/null | grep -q "version $GOLANGCI_LINT " || echo "golangci-lint $GOLANGCI_LINT"
  [ "$(biome --version 2>/dev/null)" = "Version: $BIOME" ] || echo "biome $BIOME"
  command -v dlv >/dev/null 2>&1 || echo "dlv $DLV"
  command -v claude >/dev/null 2>&1 || echo "claude latest"
}

tools_sha256() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | cut -d' ' -f1
  else
    shasum -a 256 "$1" | cut -d' ' -f1
  fi
}

# tools_fetch downloads tool's release file into the folder $2, checks it
# against its published checksum, and prints its path.
tools_fetch() {
  asset=$(tools_asset "$1" "$(uname -s)" "$(uname -m)")
  set -- "$1" "$2" $(tools_url "$1" "$asset")
  echo "tools: downloading $3" >&2
  curl -fsSL --retry 3 -o "$2/$asset" "$3"
  if [ "$4" = - ]; then
    want=$(printf '%s\n' "$BIOME_SHA256" | grep "  $asset\$" | cut -d' ' -f1) || true
  else
    curl -fsSL --retry 3 -o "$2/sums" "$4"
    want=$(grep "$asset\$" "$2/sums" | cut -d' ' -f1) || true
    [ -n "$want" ] || want=$(cut -d' ' -f1 "$2/sums")
  fi
  got=$(tools_sha256 "$2/$asset")
  if [ -z "$want" ] || [ "$got" != "$want" ]; then
    echo "tools: $asset does not match its checksum (${want:-none published}, downloaded $got)" >&2
    return 1
  fi
  echo "$2/$asset"
}

tools_unpack() {
  mkdir -p "$2"
  case $1 in
    *.zip) if command -v unzip >/dev/null 2>&1; then unzip -q "$1" -d "$2"; else tar -xf "$1" -C "$2"; fi ;;
    *) tar -xzf "$1" -C "$2" ;;
  esac
}

# tools_install installs one tool into $SE_HOME.
tools_install() {
  tmp=$(mktemp -d)
  exe=$(tools_exe "$1" "$(uname -s)")
  case $1 in
    go)
      file=$(tools_fetch go "$tmp")
      rm -rf "$SE_HOME/go"
      tools_unpack "$file" "$SE_HOME"
      ;;
    gh | golangci-lint)
      file=$(tools_fetch "$1" "$tmp")
      tools_unpack "$file" "$tmp/x"
      cp "$(find "$tmp/x" -type f -name "$exe" | head -n 1)" "$SE_HOME/bin/$exe"
      ;;
    biome)
      file=$(tools_fetch biome "$tmp")
      cp "$file" "$SE_HOME/bin/$exe"
      ;;
    dlv)
      gobin=$SE_HOME/bin
      command -v cygpath >/dev/null 2>&1 && gobin=$(cygpath -w "$gobin")
      GOBIN=$gobin go install "github.com/go-delve/delve/cmd/dlv@v$DLV"
      ;;
    claude)
      case $(uname -s) in
        MINGW* | MSYS* | CYGWIN*) powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://claude.ai/install.ps1 | iex" ;;
        *) curl -fsSL https://claude.ai/install.sh | bash ;;
      esac
      ;;
  esac
  [ -f "$SE_HOME/bin/$exe" ] && chmod +x "$SE_HOME/bin/$exe"
  rm -rf "$tmp"
}

# tools_rc puts the install's folders on the PATH of every later shell: in
# ~/.bashrc, which Git Bash reads too, and in ~/.zshrc where zsh is the shell.
tools_rc() {
  line="export PATH=\"$(tools_path):\$PATH\" # SE's tools (RUNME.sh)"
  rcs="$HOME/.bashrc"
  case ${SHELL:-} in *zsh) rcs="$rcs $HOME/.zshrc" ;; esac
  for rc in $rcs; do
    grep -qF "$line" "$rc" 2>/dev/null && continue
    printf '\n%s\n' "$line" >>"$rc"
    echo "tools: $rc puts $SE_HOME/bin on the PATH"
  done
}

if [ "${1:-}" = install ]; then
  set -eu
  differ=$(tools_differ | cut -d' ' -f1)
  if [ -n "$differ" ]; then
    mkdir -p "$SE_HOME/bin"
    for tool in $differ; do
      echo "tools: installing $tool"
      tools_install "$tool"
    done
    tools_rc
  fi
fi
