<#
.SYNOPSIS
Installs se's git hooks (public-safety check) into a repository: se itself by default, or -Repo,
such as a project that uses se as a module. Also adds the public check's local list
(.public-check.local, never checked in) to the repository's .gitignore, and sets the repository's
commit identity as work_tickets.py sync does, so its first commit already carries it.
#>
param([string]$Repo)

# Runs se's script scripts/<first argument> with the remaining arguments, as .githooks/se-script does.
function Invoke-SeScript {
    $script = Join-Path $PSScriptRoot $args[0]
    $rest = @($args | Select-Object -Skip 1)
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        uv run --no-project --quiet python $script @rest
    } else {
        python $script @rest
    }
}

# Its git goes through se's git door (scripts/git_door.py).
$seRoot = Invoke-SeScript git_door.py -C (Join-Path $PSScriptRoot '..') rev-parse --show-toplevel
if ($LASTEXITCODE -ne 0) { exit 1 }
if (-not $Repo) { $Repo = $seRoot }
$target = Invoke-SeScript git_door.py -C $Repo rev-parse --show-toplevel
if ($LASTEXITCODE -ne 0) { exit 1 }
if ($target -eq $seRoot) { $hooks = '.githooks' } else { $hooks = "$seRoot/.githooks" }
Invoke-SeScript git_door.py -C $target config core.hooksPath $hooks
if ($LASTEXITCODE -ne 0) { exit 1 }
Write-Output "core.hooksPath of $target set to $hooks"
$localList = '.public-check.local'
$ignore = Join-Path $target '.gitignore'
$text = if (Test-Path $ignore) { [IO.File]::ReadAllText($ignore) } else { '' }
$lines = $text -split "`r?`n"
if ($lines -notcontains $localList -and $lines -notcontains "/$localList") {
    if ($text -and -not $text.EndsWith("`n")) { $text += "`n" }
    [IO.File]::WriteAllText($ignore, "$text$localList`n", (New-Object Text.UTF8Encoding $false))
    Write-Output "$localList added to $ignore"
}
Invoke-SeScript work_tickets.py identity --worktree $target
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
