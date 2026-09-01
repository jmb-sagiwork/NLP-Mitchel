# Bumps the project version in pyproject.toml, email_triage/__init__.py, and
# the README download link. Called from scripts\release.bat via -File so
# cmd.exe never has to quote PowerShell code inline.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Version
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

$pyproject = Join-Path $root 'pyproject.toml'
$text = Get-Content $pyproject -Raw
$text = $text -replace '(?m)^version = "[^"]+"', ('version = "{0}"' -f $Version)
Set-Content -NoNewline -Path $pyproject -Value $text

$initFile = Join-Path $root 'src\email_triage\__init__.py'
$text = Get-Content $initFile -Raw
$text = $text -replace '__version__ = "[^"]+"', ('__version__ = "{0}"' -f $Version)
Set-Content -NoNewline -Path $initFile -Value $text

$readme = Join-Path $root 'README.md'
$text = Get-Content $readme -Raw
$text = $text -replace 'MitchelNLP-v[0-9.]+-windows-x64\.exe', ('MitchelNLP-v{0}-windows-x64.exe' -f $Version)
$text = $text -replace 'download/v[0-9.]+/', ('download/v{0}/' -f $Version)
Set-Content -NoNewline -Path $readme -Value $text

Write-Host "Bumped version to $Version"
