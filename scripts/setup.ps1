<#
.SYNOPSIS
Installs se's git hooks (public-safety check) into a repository: se itself by default, or -Repo,
such as a project that uses se as a module. Also adds the public check's local list
(.public-check.local, never checked in) to the repository's .gitignore, installs the merge driver
of generated files (merge.se-generated), and sets the repository's commit identity as work_tickets.py sync does, so its first commit already carries it. In se's own
checkout it then installs obs's adapter component obs-html where it is missing, which the docs
and decks build with (`build_docs.py --install-html`).

With -Copilot (opt-in) it then installs SE for GitHub Copilot there: `copilot.py install`
(docs/copilot.md, "Another repository"). Without it nothing else changes. Twin of setup.sh.
#>
param([string]$Repo, [switch]$Copilot)

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
# The checkout's own hooks that stop running once core.hooksPath names se's are named first.
Invoke-SeScript se_start.py stopped-hooks --repo $target --hooks $hooks
Invoke-SeScript git_door.py -C $target config core.hooksPath $hooks
if ($LASTEXITCODE -ne 0) { exit 1 }
Write-Output "core.hooksPath of $target set to $hooks"
# The merge driver of the generated files a merge regenerates (.gitattributes merge=se-generated):
# it keeps our side, and the merge's commit hooks regenerate them (scripts/generated.py "The merge").
Invoke-SeScript git_door.py -C $target config merge.se-generated.name "a generated file: keep ours, the merge's commit hooks regenerate it"
if ($LASTEXITCODE -ne 0) { exit 1 }
Invoke-SeScript git_door.py -C $target config merge.se-generated.driver true
if ($LASTEXITCODE -ne 0) { exit 1 }
Write-Output "merge driver se-generated of $target set"
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
if ($target -eq $seRoot) {
    Invoke-SeScript build_docs.py --install-html
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
if ($Copilot) {
    Invoke-SeScript copilot.py install --repo $target
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
