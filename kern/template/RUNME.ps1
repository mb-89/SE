# RUNME.ps1: finds the bash that Git for Windows ships, installing Git with winget where it is
# missing, and hands every argument to RUNME.sh beside it, passing its exit code on. The same file
# in every project; RUNME.sh does the rest. Git's winget id is RUNME.conf's line `get git winget <id>`.
function Find-GitBash {
    $roots = @()
    $git = Get-Command git -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($git) { $up = Split-Path -Parent (Split-Path -Parent $git.Source); $roots += $up, (Split-Path -Parent $up) }
    $roots += @($env:ProgramW6432, $env:ProgramFiles, ${env:ProgramFiles(x86)}) | Where-Object { $_ } | ForEach-Object { Join-Path $_ 'Git' }
    if ($env:LOCALAPPDATA) { $roots += Join-Path $env:LOCALAPPDATA 'Programs\Git' }
    foreach ($root in $roots | Where-Object { $_ }) {
        foreach ($file in 'bin\bash.exe', 'usr\bin\bash.exe') {
            $bash = Join-Path $root $file
            if (Test-Path -LiteralPath $bash -PathType Leaf) { return $bash }
        }
    }
}
$bash = Find-GitBash
if (-not $bash) {
    $found = Select-String -LiteralPath (Join-Path $PSScriptRoot 'RUNME.conf') -Pattern '^get\s+git\s+winget\s+(\S+)' -ErrorAction SilentlyContinue | Select-Object -First 1
    $winget = Get-Command winget -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not ($found -and $winget)) { [Console]::Error.WriteLine('RUNME: install Git for Windows, then run RUNME again: RUNME runs in the bash Git ships'); exit 1 }
    $id = $found.Matches[0].Groups[1].Value
    [Console]::Error.WriteLine("RUNME: installing Git for Windows: winget install --id $id -e --source winget")
    & $winget.Source install --id $id -e --source winget --accept-package-agreements --accept-source-agreements 2>&1 | ForEach-Object { [Console]::Error.WriteLine("$_") }
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
    $bash = Find-GitBash
    if (-not $bash) { [Console]::Error.WriteLine("RUNME: Git for Windows is still missing; run: winget install --id $id -e --source winget"); exit 1 }
}
# Every argument crosses in variables, never on a Windows command line, which PowerShell 5.1 and
# the bash runtime quote differently; the line below rebuilds them and execs RUNME.sh.
$all = @((Join-Path $PSScriptRoot 'RUNME.sh').Replace('\', '/')) + $args
$env:RUNME_ARGC = [string]$all.Count
for ($i = 0; $i -lt $all.Count; $i++) { [Environment]::SetEnvironmentVariable("RUNME_ARG_$i", [string]$all[$i], 'Process') }
$env:RUNME_RUN = 'runme_n=${RUNME_ARGC:-0}; runme_i=1; set --; while test "$runme_i" -lt "$runme_n"; do eval "set -- \"\$@\" \"\${RUNME_ARG_$runme_i-}\""; runme_i=$((runme_i + 1)); done; runme_s=${RUNME_ARG_0-}; runme_i=0; while test "$runme_i" -lt "$runme_n"; do unset "RUNME_ARG_$runme_i"; runme_i=$((runme_i + 1)); done; unset RUNME_ARGC RUNME_RUN runme_n runme_i; exec "$BASH" "$runme_s" "$@"'
& $bash -c 'eval $RUNME_RUN'
exit $LASTEXITCODE
