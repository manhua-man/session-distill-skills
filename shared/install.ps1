<#
.SYNOPSIS
    Install session-distill Deep Distill skills for one or more AI platforms.

.DESCRIPTION
    Copies platform packages from this repo into each tool's skills directory,
    optionally installs slash-command stubs, and syncs shared deep_distill_lib.

.PARAMETER Platforms
    Comma-separated list. All supported:
    cursor, grok, codex, claude, hermes, antigravity, opencode

.PARAMETER SyncOnly
    Only run shared/sync_deep_distill_lib.py (no file copies).

.PARAMETER RepoRoot
    Path to session-distill-skills repo root. Defaults to parent of shared/.

.EXAMPLE
    .\shared\install.ps1

.EXAMPLE
    .\shared\install.ps1 -Platforms cursor,grok,hermes,antigravity

.EXAMPLE
    .\shared\install.ps1 -SyncOnly
#>

[CmdletBinding()]
param(
    [string]$Platforms = 'cursor,grok,codex,claude,hermes,antigravity,opencode',
    [switch]$SyncOnly,
    [string]$RepoRoot = ''
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
}

function Copy-Tree {
    param(
        [string]$Source,
        [string]$Destination
    )
    if (-not (Test-Path $Source)) {
        throw "Missing source: $Source"
    }
    if (Test-Path $Destination) {
        Remove-Item -LiteralPath $Destination -Recurse -Force
    }
    $parent = Split-Path -Parent $Destination
    if ($parent -and -not (Test-Path $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    Copy-Item -LiteralPath $Source -Destination $Destination -Recurse -Force
    Write-Host "  installed -> $Destination"
}

function Install-OptionalCommand {
    param(
        [string]$Source,
        [string]$Destination
    )
    if (-not (Test-Path $Source)) {
        return
    }
    $parent = Split-Path -Parent $Destination
    if ($parent -and -not (Test-Path $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    Copy-Item -LiteralPath $Source -Destination $Destination -Force
    Write-Host "  command   -> $Destination"
}

$PlatformDefs = @{
    cursor = @{
        Package = 'cursor-session-distill'
        SkillDest = Join-Path $env:USERPROFILE '.cursor\skills\session-distill'
        CommandSrc = 'commands\session-distill.md'
        CommandDest = Join-Path $env:USERPROFILE '.cursor\commands\session-distill.md'
    }
    grok = @{
        Package = 'grok-session-distill'
        SkillDest = Join-Path $env:USERPROFILE '.grok\skills\session-distill'
        CommandSrc = 'commands\session-distill.md'
        CommandDest = Join-Path $env:USERPROFILE '.grok\commands\session-distill.md'
    }
    codex = @{
        Package = 'codex-session-distill'
        SkillDest = Join-Path $env:USERPROFILE '.codex\skills\manhua\session-distill'
        CommandSrc = 'commands\session-distill.md'
        CommandDest = Join-Path $env:USERPROFILE '.codex\commands\session-distill.md'
    }
    claude = @{
        Package = 'session-distill'
        SkillDest = Join-Path $env:USERPROFILE '.claude\skills\manhua\session-distill'
        CommandSrc = 'commands\session-distill.md'
        CommandDest = Join-Path $env:USERPROFILE '.claude\commands\session-distill.md'
    }
    hermes = @{
        Package = 'hermes-session-distill'
        SkillDest = Join-Path $env:LOCALAPPDATA 'hermes\skills\session-distill'
        CommandSrc = 'commands\session-distill.md'
        CommandDest = Join-Path $env:LOCALAPPDATA 'hermes\commands\session-distill.md'
    }
    antigravity = @{
        Package = 'antigravity-session-distill'
        SkillDest = Join-Path $env:USERPROFILE '.gemini\antigravity-cli\skills\session-distill'
        CommandSrc = 'commands\session-distill.md'
        CommandDest = Join-Path $env:USERPROFILE '.gemini\antigravity-cli\commands\session-distill.md'
    }
    opencode = @{
        Package = 'opencode-session-distill'
        SkillDest = Join-Path $env:USERPROFILE '.config\opencode\skills\session-distill'
        CommandSrc = 'commands\session-distill.md'
        CommandDest = Join-Path $env:USERPROFILE '.config\opencode\commands\session-distill.md'
    }
}

$selected = @(
    $Platforms.Split(',') |
        ForEach-Object { $_.Trim().ToLower() } |
        Where-Object { $_ }
) | Select-Object -Unique

Write-Host "Repo: $RepoRoot"

$syncScript = Join-Path $RepoRoot 'shared\sync_deep_distill_lib.py'
if (-not (Test-Path $syncScript)) {
    throw "sync script not found: $syncScript"
}
python $syncScript
if ($LASTEXITCODE -ne 0) {
    throw "sync_deep_distill_lib.py failed"
}

if ($SyncOnly) {
    Write-Host 'SyncOnly complete.'
    exit 0
}

foreach ($name in $selected) {
    if (-not $PlatformDefs.ContainsKey($name)) {
        throw "Unknown platform: $name"
    }
    $def = $PlatformDefs[$name]
    $src = Join-Path $RepoRoot $def.Package
    Write-Host "==> $name"
    Copy-Tree -Source $src -Destination $def.SkillDest
    if ($def.CommandSrc -and $def.CommandDest) {
        Install-OptionalCommand -Source (Join-Path $src $def.CommandSrc) -Destination $def.CommandDest
    }
}

Write-Host 'Done. Deep Distill: deep-distill-run.py --batch-size 3 → answer-me → check-work → mark distilled'
