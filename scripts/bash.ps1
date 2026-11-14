<#
.SYNOPSIS
Runs a shell script in the bash that Git for Windows ships, from PowerShell, so a PowerShell line
does not depend on a bare `bash` on PATH (missing on Windows, or WSL's launcher).

  scripts/bash.ps1 <script> [<argument> ...]

The script and every argument go through unchanged, and the script's exit code is returned. The
choice of bash is one pure function, Select-SeBash, of git's location and the paths that exist;
the rest of this file only gathers those inputs and starts the bash. With no bash to start it
prints one line naming what to install and exits 127.

Dot-sourced (`. scripts/bash.ps1`) it only defines its functions.
#>

# The one line printed where no bash can be started.
$SeBashInstall = 'SE needs the bash that Git for Windows ships: install Git for Windows (winget install --id Git.Git -e, or https://git-scm.com/download/win)'

# Git's own wrapper: it puts Git's usr\bin and mingw64\bin on PATH before it starts usr\bin\bash.exe,
# so a script finds uname, curl and the rest from a PowerShell whose PATH has none of them. The
# plain usr\bin\bash.exe is the fallback where an install lacks the wrapper.
$SeBashFiles = @('bin\bash.exe', 'usr\bin\bash.exe')

# The Git roots to look in, in order: those git's location implies (Git\cmd\git.exe,
# Git\bin\git.exe, Git\mingw64\bin\git.exe), then the usual install places. Pure.
function Get-SeGitRoots {
    param([string]$Git, [string[]]$Places = @())
    $roots = @()
    if ($Git) {
        $dir = Split-Path -Parent $Git
        $up = Split-Path -Parent $dir
        if ($up) {
            $roots += $up
            $upper = Split-Path -Parent $up
            if ($upper) { $roots += $upper }
        }
    }
    @($roots + @($Places | Where-Object { $_ }))
}

# Every bash file worth testing for existence, in the order Select-SeBash prefers them. Pure.
function Get-SeBashCandidates {
    param([string]$Git, [string[]]$Places = @())
    foreach ($root in Get-SeGitRoots -Git $Git -Places $Places) {
        foreach ($file in $SeBashFiles) { Join-Path $root $file }
    }
}

# Whether a bash on PATH is WSL's launcher rather than a bash: the one in System32 (or its
# redirections) and the Store alias under WindowsApps. Pure.
function Test-SeWslLauncher {
    param([string]$Path)
    $Path -match '(?i)[\\/](System32|Sysnative|SysWOW64|WindowsApps)[\\/]bash\.exe$'
}

<#
The choice, a pure function: git's location (-Git, empty where git is not on PATH), the usual
Git install places (-Places), the bash PATH names (-PathBash, empty where none) and which of the
candidate paths exist (-Exists). Returns Case and Bash:
  git      Git's bash beside git
  install  Git's bash in a usual install place
  path     a bash on PATH that is not WSL's launcher
  wsl      only WSL's launcher on PATH: no bash (Bash empty)
  none     nothing found (Bash empty)
#>
function Select-SeBash {
    param([string]$Git, [string[]]$Places = @(), [string]$PathBash, [string[]]$Exists = @())
    foreach ($candidate in Get-SeBashCandidates -Git $Git) {
        if ($Exists -contains $candidate) { return [pscustomobject]@{ Case = 'git'; Bash = $candidate } }
    }
    foreach ($candidate in Get-SeBashCandidates -Places $Places) {
        if ($Exists -contains $candidate) { return [pscustomobject]@{ Case = 'install'; Bash = $candidate } }
    }
    if ($PathBash) {
        if (Test-SeWslLauncher $PathBash) { return [pscustomobject]@{ Case = 'wsl'; Bash = '' } }
        return [pscustomobject]@{ Case = 'path'; Bash = $PathBash }
    }
    [pscustomobject]@{ Case = 'none'; Bash = '' }
}

# The usual install places of Git for Windows: machine-wide and per user.
function Get-SeGitPlaces {
    @($env:ProgramW6432, $env:ProgramFiles, ${env:ProgramFiles(x86)}) | Where-Object { $_ } |
        ForEach-Object { Join-Path $_ 'Git' }
    if ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA 'Programs\Git' }
}

# The bash code -c runs: it rebuilds the argument list from SE_BASH_ARGC and SE_BASH_ARG_<i>, so
# no argument crosses a Windows command line, whose quoting PowerShell 5.1 and the MSYS runtime
# read differently, and execs the script with it. It holds no newline, no glob character and no
# double space, since the command line expands it unquoted (eval $SE_BASH_RUN).
$SeBashRun = 'se_n=${SE_BASH_ARGC:-0}; se_i=1; set --; while test "$se_i" -lt "$se_n"; do eval "set -- \"\$@\" \"\${SE_BASH_ARG_$se_i-}\""; se_i=$((se_i + 1)); done; se_script=${SE_BASH_ARG_0-}; se_i=0; while test "$se_i" -lt "$se_n"; do unset "SE_BASH_ARG_$se_i"; se_i=$((se_i + 1)); done; unset SE_BASH_ARGC SE_BASH_RUN se_n se_i; exec "$BASH" "$se_script" "$@"'

if ($MyInvocation.InvocationName -eq '.') { return }

if ($args.Count -lt 1) {
    [Console]::Error.WriteLine('usage: bash.ps1 <script> [<argument> ...]')
    exit 2
}

$git = Get-Command git -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
$pathBash = Get-Command bash -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
$gitPath = if ($git) { $git.Source } else { '' }
$pathBashPath = if ($pathBash) { $pathBash.Source } else { '' }
$places = @(Get-SeGitPlaces)
$exists = @(Get-SeBashCandidates -Git $gitPath -Places $places | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf })
$choice = Select-SeBash -Git $gitPath -Places $places -PathBash $pathBashPath -Exists $exists
if (-not $choice.Bash) {
    [Console]::Error.WriteLine($SeBashInstall)
    exit 127
}

$env:SE_BASH_ARGC = [string]$args.Count
for ($i = 0; $i -lt $args.Count; $i++) {
    [Environment]::SetEnvironmentVariable("SE_BASH_ARG_$i", [string]$args[$i], 'Process')
}
$env:SE_BASH_RUN = $SeBashRun
& $choice.Bash -c 'eval $SE_BASH_RUN'
exit $LASTEXITCODE
