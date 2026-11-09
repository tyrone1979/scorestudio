# Install ComposerChat plugin into MuseScore Studio 4 Plugins folder.
param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path,
    [string]$PluginsDir = $(Join-Path $env:USERPROFILE 'Documents\MuseScore4\Plugins')
)

$ErrorActionPreference = 'Stop'

$src = Join-Path $ProjectRoot 'musescore_plugin\ComposerChat'
$dst = Join-Path $PluginsDir 'ComposerChat'

if (-not (Test-Path $src)) {
    throw "Plugin source not found: $src"
}

New-Item -ItemType Directory -Force -Path $PluginsDir | Out-Null
New-Item -ItemType Directory -Force -Path $dst | Out-Null

# Resolve Python: prefer project venv
$pyCandidates = @(
    (Join-Path $ProjectRoot 'venv\Scripts\python.exe'),
    (Join-Path $ProjectRoot '.venv\Scripts\python.exe'),
    (Get-Command python -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source)
) | Where-Object { $_ -and (Test-Path $_) }

if (-not $pyCandidates) {
    throw 'No Python found. Create venv or put python on PATH.'
}
$python = $pyCandidates[0]

$outDir = Join-Path $ProjectRoot 'scores\musescore_out'
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

# Copy plugin files (overwrite)
foreach ($name in @('ComposerChat.qml', 'generate.cmd', 'generate_silent.vbs', 'composerchat.png')) {
    $from = Join-Path $src $name
    if (Test-Path $from) {
        Copy-Item $from (Join-Path $dst $name) -Force
    }
}

# Write machine-local config (forward slashes for QML/JSON comfort)
function To-Fwd([string]$p) { return ($p -replace '\\', '/') }
$configObj = [ordered]@{
    project_root = (To-Fwd $ProjectRoot)
    python       = (To-Fwd $python)
    out_dir      = (To-Fwd $outDir)
}
$config = ($configObj | ConvertTo-Json)
# UTF-8 without BOM — QML JSON.parse rejects BOM
$utf8 = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText((Join-Path $dst 'config.json'), $config + "`n", $utf8)
[System.IO.File]::WriteAllText((Join-Path $src 'config.json'), $config + "`n", $utf8)

Write-Host "Installed ComposerChat plugin:"
Write-Host "  $dst"
Write-Host "Python: $python"
Write-Host "Out:    $outDir"
Write-Host ""
Write-Host "Next in MuseScore Studio:"
Write-Host "  1. Restart MuseScore (or reload plugins)"
Write-Host "  2. Home → Plugins → enable 'ComposerChat Generate'"
Write-Host "  3. Run it from Plugins → Composing tools"
