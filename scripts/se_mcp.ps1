# The launcher of SE's MCP door (`se mcp`, docs/start.md "The MCP door"), the PowerShell twin of se_mcp.sh,
# which owns what it does; the two answer alike.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File se_mcp.ps1 --root <project>
#
# Standard output carries MCP alone; everything else goes to <project>\.se\.runtime\mcp.log (the
# binary's own stderr to mcp-door.log beside it), else the system's temporary folder; in a plugin
# install whose session folder has no .git in it or above it, to ~\.se\.runtime instead. A plugin
# install chooses its root as se_mcp.sh does: the plugin's root is PLUGIN_ROOT, else CLAUDE_PLUGIN_ROOT,
# and the root SE_SESSION_CWD, else that host's session folder (COPILOT_SESSION_CWD, CLAUDE_PROJECT_DIR),
# with no parent-cwd backstop.
$ErrorActionPreference = 'Stop'
$seRoot = Split-Path -Parent $PSScriptRoot
$root = ''
for ($i = 0; $i -lt $args.Count; $i++) {
    if ($args[$i] -eq '--root' -and $i + 1 -lt $args.Count) { $root = [string]$args[$i + 1]; $i++ }
    elseif ([string]$args[$i] -like '--root=*') { $root = ([string]$args[$i]).Substring(7) }
}
if (-not $root) { $root = (Get-Location).Path }
try { $root = (Resolve-Path -LiteralPath $root).Path } catch { $root = (Get-Location).Path }

function LogFolder([string]$folder, [bool]$session, [string]$homeFolder) { # the folder the launcher logs in
    $base = if ($session) { $homeFolder } else { $folder }
    return Join-Path (Join-Path $base '.se') '.runtime'
}
function SessionFolder([string]$folder, [string]$plugin) { # whether the plugin case's root is a session folder, no checkout
    return (-not (Same $folder $plugin)) -and -not (Test-Path -LiteralPath (Join-Path $folder '.git'))
}
function Runtime([string]$folder, [bool]$session = $false) { # the folder the launcher logs to for that root
    $runtime = LogFolder $folder $session $HOME
    try { New-Item -ItemType Directory -Force -Path $runtime | Out-Null } catch { $runtime = [IO.Path]::GetTempPath() }
    return $runtime
}
function Note([string]$text) {
    try { [IO.File]::AppendAllText($log, "$([DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')) se_mcp.ps1: $text`n") } catch {}
}
$windows = [IO.Path]::DirectorySeparatorChar -eq '\'
function Folder([string]$path) { # the folder's full path, or '' where it is none
    try { $item = Get-Item -LiteralPath $path -Force -ErrorAction Stop } catch { return '' }
    if (-not $item.PSIsContainer) { return '' }
    $full = $item.FullName.TrimEnd('\', '/')
    if (-not $full) { return '/' }
    if ($full.EndsWith(':')) { return $full + '\' }
    return $full
}
function Same([string]$a, [string]$b) {
    $how = if ($windows) { [StringComparison]::OrdinalIgnoreCase } else { [StringComparison]::Ordinal }
    return [string]::Equals($a, $b, $how)
}
function Inside([string]$path, [string]$folder) { # whether path is folder or lies inside it
    $sep = [IO.Path]::DirectorySeparatorChar
    $how = if ($windows) { [StringComparison]::OrdinalIgnoreCase } else { [StringComparison]::Ordinal }
    return ($path.TrimEnd($sep) + $sep).StartsWith($folder.TrimEnd($sep) + $sep, $how)
}
function PluginProject([string]$plugin, [string[]]$names) { # the root a plugin install serves; $script:pluginFound where a source counts
    $script:pluginFound = $false
    $dir = ''
    $source = ''
    foreach ($name in $names) {
        $value = [Environment]::GetEnvironmentVariable($name)
        if ($value -and [IO.Path]::IsPathRooted($value)) {
            $dir = Folder $value
            if ($dir) { $source = "$name=$value"; break }
        }
    }
    $chosen = $plugin
    if ($source) {
        $script:pluginFound = $true
        if (-not (Inside $dir $plugin)) {
            $chosen = $dir
            while ($chosen -and -not (Test-Path -LiteralPath (Join-Path $chosen '.git'))) { $chosen = Split-Path -Parent $chosen }
            if (-not $chosen) { $chosen = $dir }
        }
    } else {
        $source = "no variable set ($($names -join ', '))"
    }
    $script:log = Join-Path (Runtime $chosen (SessionFolder $chosen $plugin)) 'mcp.log'
    Note "plugin ${plugin}: root $chosen from $source"
    return $chosen
}

$session = $false
$pluginRoot = $env:PLUGIN_ROOT
$sessionNames = @('SE_SESSION_CWD', 'COPILOT_SESSION_CWD')
if (-not $pluginRoot -and $env:CLAUDE_PLUGIN_ROOT) {
    $pluginRoot = $env:CLAUDE_PLUGIN_ROOT
    $sessionNames = @('SE_SESSION_CWD', 'CLAUDE_PROJECT_DIR')
}
if ($pluginRoot -and $env:SE_MCP_PLUGIN_PROJECT -ne 'off') {
    $plugin = Folder $pluginRoot
    if ($plugin -and (Same $plugin (Folder $seRoot)) -and (Same $plugin (Folder $root))) {
        Remove-Item Env:SE_MCP_PLUGIN_FOLDER -ErrorAction SilentlyContinue
        $chosen = PluginProject $plugin $sessionNames
        if ($script:pluginFound) {
            if (-not (Same $chosen $plugin)) {
                $root = $chosen
                $session = SessionFolder $chosen $plugin
                $next = "$chosen/scripts/se_mcp.ps1"
                if ((Test-Path -LiteralPath $next -PathType Leaf) -and (Test-Path -LiteralPath "$chosen/components/release.toml" -PathType Leaf)) {
                    $shell = (Get-Process -Id $PID).Path
                    $handover = Start-Process -FilePath $shell -NoNewWindow -Wait -PassThru -ArgumentList @(
                        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$next`"", '--root', "`"$chosen`"")
                    exit $handover.ExitCode
                }
            }
        } elseif (-not (Test-Path -LiteralPath (Join-Path $plugin '.git'))) {
            $env:SE_MCP_PLUGIN_FOLDER = $plugin
        }
    }
}

$runtime = Runtime $root $session
$log = Join-Path $runtime 'mcp.log'

$version = ''
$pin = Join-Path (Join-Path $seRoot 'components') 'release.toml'
if (Test-Path -LiteralPath $pin) {
    foreach ($line in [IO.File]::ReadAllLines($pin)) {
        if ($line -match '^version\s*=\s*"([^"]*)"') { $version = $Matches[1]; break }
    }
}
$suffix = if ($windows) { '.exe' } else { '' }
$binDir = Join-Path (Join-Path $HOME '.se') 'bin'
$bin = $env:SE_MCP_BIN
if (-not $bin) { $bin = Join-Path $binDir "se-$version$suffix" }
$sums = Join-Path $binDir "se-$version.SHA256SUMS"

if (($version -or $env:SE_MCP_BIN) -and (Test-Path -LiteralPath $bin -PathType Leaf)) {
    Note "starting $bin mcp --root $root --home $seRoot"
    $quoted = @('mcp', '--root', "`"$root`"", '--home', "`"$seRoot`"")
    # -NoNewWindow: the binary inherits this process's standard input and output, which carry MCP.
    $door = Start-Process -FilePath $bin -ArgumentList $quoted -NoNewWindow -Wait -PassThru `
        -RedirectStandardError (Join-Path $runtime 'mcp-door.log')
    exit $door.ExitCode
}

# The binary is missing: answer as a door of one tool.
if (-not $version) { $why = "no release pin at $pin" }
elseif ($env:SE_MCP_BIN) { $why = "SE_MCP_BIN names $bin, which is no file" }
elseif (Test-Path -LiteralPath $sums) { $why = "se $version is not in place at $bin yet; SE's start found its release and fetches it" }
else { $why = "se $version is not in place at $bin" }
$remedy = "run setup in the project: cd '$root'; bash '$seRoot/scripts/bootstrap.sh' --hook, then restart the se MCP server"
Note "not installed: $why"
function Json([string]$text) { return $text.Replace('\', '\\').Replace('"', '\"').Replace("`t", ' ') }
$message = Json $why
$remedy = Json $remedy
$out = New-Object IO.StreamWriter([Console]::OpenStandardOutput(), (New-Object Text.UTF8Encoding($false)))
$out.NewLine = "`n"
$out.AutoFlush = $true
$in = New-Object IO.StreamReader([Console]::OpenStandardInput(), (New-Object Text.UTF8Encoding($false)))
function Answer([string]$id, [string]$body) { $out.WriteLine('{"jsonrpc":"2.0","id":' + $id + ',' + $body + '}') }
while ($null -ne ($line = $in.ReadLine())) {
    if ($line -notmatch '"method"\s*:\s*"([^"]+)"') { continue }
    $method = $Matches[1]
    if ($line -notmatch '"id"\s*:\s*("[^"]*"|-?[0-9]+)') { continue }  # a notification
    $id = $Matches[1]
    switch ($method) {
        'initialize' {
            $protocol = '2025-06-18'
            if ($line -match '"protocolVersion"\s*:\s*"([^"]+)"') { $protocol = $Matches[1] }
            Answer $id ('"result":{"protocolVersion":"' + $protocol + '","capabilities":{"tools":{}},"serverInfo":{"name":"se","version":"' + (Json $version) + '"},"instructions":"not-installed: ' + $message + '. Remedy: ' + $remedy + '."}')
        }
        'tools/list' {
            Answer $id '"result":{"tools":[{"name":"status","title":"status","description":"Whether SE''s core runs. SE''s binary is not installed here: every call says what to run.","inputSchema":{"type":"object","properties":{},"additionalProperties":false},"annotations":{"readOnlyHint":true}}]}'
        }
        'tools/call' {
            Answer $id ('"result":{"isError":true,"content":[{"type":"text","text":"not-installed: ' + $message + '. Remedy: ' + $remedy + '."}],"structuredContent":{"error":"not-installed","message":"' + $message + '","remedy":"' + $remedy + '"}}')
        }
        'ping' { Answer $id '"result":{}' }
        default { Answer $id ('"error":{"code":-32601,"message":"se_mcp.ps1 offers no ' + (Json $method) + ' while SE''s binary is not installed"}') }
    }
}
