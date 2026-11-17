$ErrorActionPreference = 'Stop'

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$skillRoot = Join-Path $env:USERPROFILE '.gemini\config\skills\game-asset-studio'
New-Item -ItemType Directory -Path $skillRoot -Force | Out-Null

Copy-Item -Force (Join-Path $projectRoot 'skill\SKILL.md') (Join-Path $skillRoot 'SKILL.md')
Copy-Item -Force (Join-Path $PSScriptRoot 'Start-XMU21-Asset-Studio.ps1') (Join-Path $skillRoot 'Start-XMU21-Asset-Studio.ps1')
Copy-Item -Force (Join-Path $PSScriptRoot 'Register-XMU21-Asset-Studio.ps1') (Join-Path $skillRoot 'Register-XMU21-Asset-Studio.ps1')

Write-Output "AGY game asset studio skill installed: $skillRoot"

