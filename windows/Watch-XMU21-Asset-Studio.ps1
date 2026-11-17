$ErrorActionPreference = 'Stop'

$startScript = Join-Path $PSScriptRoot 'Start-XMU21-Asset-Studio.ps1'
$logFile = Join-Path $env:LOCALAPPDATA 'AGY-Asset-Studio-tunnel.log'
$healthUrl = 'http://127.0.0.1:18333/health'

while ($true) {
    $response = & curl.exe --silent --fail --max-time 5 $healthUrl
    $isHealthy = $LASTEXITCODE -eq 0 -and ($response | Select-String -SimpleMatch '"service":"agy-game-asset-studio"' -Quiet)
    if (-not $isHealthy) {
        Add-Content -Encoding UTF8 -Path $logFile -Value "$(Get-Date -Format o) Reconnecting xmu21 asset studio"
        & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $startScript 2>&1 |
            Out-File -FilePath $logFile -Encoding UTF8 -Append
        if ($LASTEXITCODE -ne 0) {
            Add-Content -Encoding UTF8 -Path $logFile -Value "$(Get-Date -Format o) Reconnect failed"
        }
    }
    Start-Sleep -Seconds 30
}

