<#
.SYNOPSIS
Installs se's git hooks (public-safety check) into a repository: se itself by default, or -Repo,
such as a project that uses se as a module.
#>
param([string]$Repo)

$seRoot = git -C (Join-Path $PSScriptRoot '..') rev-parse --show-toplevel
if ($LASTEXITCODE -ne 0) { exit 1 }
if (-not $Repo) { $Repo = $seRoot }
$target = git -C $Repo rev-parse --show-toplevel
if ($LASTEXITCODE -ne 0) { exit 1 }
if ($target -eq $seRoot) { $hooks = '.githooks' } else { $hooks = "$seRoot/.githooks" }
git -C $target config core.hooksPath $hooks
if ($LASTEXITCODE -ne 0) { exit 1 }
Write-Output "core.hooksPath of $target set to $hooks"
