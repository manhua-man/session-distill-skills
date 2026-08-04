<#
.SYNOPSIS
    Install session-distill Deep Distill skills for one or more AI platforms.

.DESCRIPTION
    Copies platform packages from this repo into each tool's skills directory,
    optionally installs slash-command stubs, and validates shared distill_core.

.PARAMETER Platforms
    Comma-separated list. All supported:
    cursor, grok, codex, claude, hermes, antigravity, opencode

.PARAMETER SyncOnly
    Only validate shared distill_core copies (no file copies).

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
    [string]$RepoRoot = '',
    [string]$BackupRoot = '',
    [switch]$WhatIf
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
}

if ([string]::IsNullOrWhiteSpace($BackupRoot)) {
    $BackupRoot = Join-Path (Join-Path $env:TEMP 'session-distill-install-backups') (Get-Date -Format 'yyyyMMdd-HHmmss')
}

function Copy-Tree {
    param(
        [string]$Source,
        [string]$Destination,
        [string]$Label
    )
    if (-not (Test-Path $Source)) {
        throw "Missing source: $Source"
    }
    $parent = Split-Path -Parent $Destination
    if ($parent -and -not (Test-Path $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $staging = Join-Path $parent ("." + (Split-Path -Leaf $Destination) + ".staging-" + [guid]::NewGuid().ToString('N'))
    $backup = $null
    try {
        New-Item -ItemType Directory -Path $staging -Force | Out-Null
        Get-ChildItem -LiteralPath $Source -Force | ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination $staging -Recurse -Force
        }
        if (Test-Path $Destination) {
            New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null
            $backup = Join-Path $BackupRoot ("$Label-" + (Get-Date -Format 'yyyyMMdd-HHmmssfff'))
            Move-Item -LiteralPath $Destination -Destination $backup -ErrorAction Stop
        }
        Move-Item -LiteralPath $staging -Destination $Destination -ErrorAction Stop
        Write-Host "  installed -> $Destination"
        if ($backup) {
            Write-Host "  backup    -> $backup"
        }
    }
    catch {
        if ((Test-Path $backup) -and -not (Test-Path $Destination)) {
            Move-Item -LiteralPath $backup -Destination $Destination -ErrorAction SilentlyContinue
        }
        if (Test-Path $staging) {
            Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
        }
        throw
    }
}

function Install-OptionalCommand {
    param(
        [string]$Source,
        [string]$Destination,
        [string]$Label
    )
    if (-not (Test-Path $Source)) {
        return
    }
    $parent = Split-Path -Parent $Destination
    if ($parent -and -not (Test-Path $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $backup = $null
    try {
        if (Test-Path $Destination) {
            New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null
            $backup = Join-Path $BackupRoot ("$Label-command-" + (Get-Date -Format 'yyyyMMdd-HHmmssfff') + '.md')
            Move-Item -LiteralPath $Destination -Destination $backup -ErrorAction Stop
        }
        Copy-Item -LiteralPath $Source -Destination $Destination -Force -ErrorAction Stop
        Write-Host "  command   -> $Destination"
        if ($backup) {
            Write-Host "  backup    -> $backup"
        }
    }
    catch {
        if ((Test-Path $backup) -and -not (Test-Path $Destination)) {
            Move-Item -LiteralPath $backup -Destination $Destination -ErrorAction SilentlyContinue
        }
        throw
    }
}

$PlatformDefs = @{
    cursor = @{
        Package = 'adapters\cursor-session-distill'
        SkillDest = Join-Path $env:USERPROFILE '.cursor\skills\session-distill'
        CommandSrc = 'commands\session-distill.md'
        CommandDest = Join-Path $env:USERPROFILE '.cursor\commands\session-distill.md'
    }
    grok = @{
        Package = 'adapters\grok-session-distill'
        SkillDest = Join-Path $env:USERPROFILE '.grok\skills\session-distill'
        CommandSrc = 'commands\session-distill.md'
        CommandDest = Join-Path $env:USERPROFILE '.grok\commands\session-distill.md'
    }
    codex = @{
        Package = 'adapters\codex-session-distill'
        SkillDest = Join-Path $env:USERPROFILE '.codex\skills\manhua\session-distill'
        CommandSrc = 'commands\session-distill.md'
        CommandDest = Join-Path $env:USERPROFILE '.codex\commands\session-distill.md'
    }
    claude = @{
        Package = 'adapters\claude-session-distill'
        SkillDest = Join-Path $env:USERPROFILE '.claude\skills\manhua\session-distill'
        CommandSrc = 'commands\session-distill.md'
        CommandDest = Join-Path $env:USERPROFILE '.claude\commands\session-distill.md'
    }
    hermes = @{
        Package = 'adapters\hermes-session-distill'
        SkillDest = Join-Path $env:LOCALAPPDATA 'hermes\skills\session-distill'
        CommandSrc = 'commands\session-distill.md'
        CommandDest = Join-Path $env:LOCALAPPDATA 'hermes\commands\session-distill.md'
    }
    antigravity = @{
        Package = 'adapters\antigravity-session-distill'
        SkillDest = Join-Path $env:USERPROFILE '.gemini\antigravity-cli\skills\session-distill'
        CommandSrc = 'commands\session-distill.md'
        CommandDest = Join-Path $env:USERPROFILE '.gemini\antigravity-cli\commands\session-distill.md'
    }
    opencode = @{
        Package = 'adapters\opencode-session-distill'
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
Write-Host "Backups: $BackupRoot"

$syncScript = Join-Path $RepoRoot 'scripts\sync-repo-distill-core.py'
if (-not (Test-Path $syncScript)) {
    throw "shared-core check script not found: $syncScript"
}
if ($WhatIf) {
    Write-Host "WhatIf: would validate shared distill_core copies"
}
else {
    python $syncScript --check
    if ($LASTEXITCODE -ne 0) {
        throw "shared distill_core copies are out of sync; run scripts\\sync-repo-distill-core.py first"
    }
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
    if ($WhatIf) {
        Write-Host "WhatIf: would install -> $($def.SkillDest)"
        if ($def.CommandSrc -and $def.CommandDest) {
            Write-Host "WhatIf: would install -> $($def.CommandDest)"
        }
        continue
    }
    Copy-Tree -Source $src -Destination $def.SkillDest -Label $name
    if ($def.CommandSrc -and $def.CommandDest) {
        Install-OptionalCommand -Source (Join-Path $src $def.CommandSrc) -Destination $def.CommandDest -Label $name
    }
}

Write-Host 'Done. Deep Distill: deep-distill-run.py --batch-size 3 → answer-me → check-work → mark distilled'
if (-not $WhatIf) {
    Write-Host "Previous installs, if replaced, are retained under: $BackupRoot"
}
