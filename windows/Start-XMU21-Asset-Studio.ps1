$ErrorActionPreference = 'Stop'

$port = 18333
$healthUrl = "http://127.0.0.1:$port/health"
$remote = 'xmu21-a800'
$remoteProject = '/data/xmu/ym/services/AGY-GameAsset-Studio'
$ssh = (Get-Command ssh.exe).Source

function Test-AssetStudio {
    $response = & curl.exe --silent --fail --max-time 5 $healthUrl
    return ($LASTEXITCODE -eq 0 -and ($response | Select-String -SimpleMatch '"service":"agy-game-asset-studio"' -Quiet))
}

if (Test-AssetStudio) {
    Write-Output "AGY Game Asset Studio is accessible at $healthUrl"
    exit 0
}

$listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
    Where-Object LocalAddress -EQ '127.0.0.1' |
    Select-Object -First 1
if ($listener) {
    $owner = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
    if ($owner.Name -ne 'ssh.exe' -or $owner.CommandLine -notmatch '127.0.0.1:18333:127.0.0.1:18333') {
        throw "Port $port is occupied by an unrelated service."
    }
    Stop-Process -Id $listener.OwningProcess -Force
}

& $ssh -T -n -o BatchMode=yes -o ConnectTimeout=8 -o ConnectionAttempts=1 $remote "curl -fsS --max-time 5 http://127.0.0.1:18333/health > /dev/null || (cd $remoteProject && bash scripts/start.sh)"
if ($LASTEXITCODE -ne 0) {
    throw "Cannot start the asset studio on xmu21."
}

$arguments = @(
    '-N', '-T',
    '-L', '127.0.0.1:18333:127.0.0.1:18333',
    '-o', 'BatchMode=yes',
    '-o', 'ExitOnForwardFailure=yes',
    '-o', 'ServerAliveInterval=20',
    '-o', 'ServerAliveCountMax=3',
    '-o', 'ConnectTimeout=8',
    $remote
)
$tunnel = Start-Process -FilePath $ssh -ArgumentList $arguments -WindowStyle Hidden -PassThru

for ($index = 0; $index -lt 15; $index++) {
    if ($tunnel.HasExited) {
        throw "SSH tunnel terminated with exit code $($tunnel.ExitCode)."
    }
    if (Test-AssetStudio) {
        Write-Output "AGY Game Asset Studio is accessible at $healthUrl"
        exit 0
    }
    Start-Sleep -Seconds 1
}
throw 'Failed to verify the local xmu21 asset studio tunnel.'

