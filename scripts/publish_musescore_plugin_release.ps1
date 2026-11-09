# Publish MuseScore plugin GitHub release (tyrone1979/scorestudio).
# Prerequisites: git remote "github", SSH or HTTPS auth to GitHub, gh logged in.
param(
    [string]$Tag = 'musescore-plugin-v1.0.0',
    [string]$Zip = (Join-Path (Resolve-Path (Join-Path $PSScriptRoot '..')).Path '.tmp\ComposerChat-MuseScore-Plugin-v1.0.0.zip'),
    [string]$Repo = 'tyrone1979/scorestudio'
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root

if (-not (Test-Path $Zip)) {
    throw "Release zip missing: $Zip — rebuild with the packaging steps first."
}

$remotes = git remote
if ($remotes -notcontains 'github') {
    git remote add github "git@github.com:$Repo.git"
}

git push github main
git tag -f $Tag HEAD
git push github $Tag --force

$notes = @"
## MuseScore Studio plugin

Deterministic score generation inside MuseScore Studio 4.4+ (tested on 4.7).

### Install
1. Unzip ``ComposerChat-MuseScore-Plugin-v1.0.0.zip``
2. From a ComposerChat checkout with venv:
   ``powershell -ExecutionPolicy Bypass -File scripts\install_musescore_plugin.ps1``
3. Restart MuseScore → enable **ComposerChat Generate**

### CLI
``````
python generate_score.py --pack chorale --bars 16 --out out.musicxml
``````

See ``musescore_plugin/README.md``.
"@

gh release create $Tag $Zip `
  --repo $Repo `
  --title "MuseScore plugin $Tag" `
  --notes $notes `
  --latest=false

Write-Host "Done: https://github.com/$Repo/releases/tag/$Tag"
