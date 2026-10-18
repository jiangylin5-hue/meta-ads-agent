param(
    [int]$Port = 8010,
    [string]$HostName = "127.0.0.1"
)

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "D:\anaconda\python.exe"
}
if (-not (Test-Path $Python)) {
    $Python = (Get-Command python).Source
}

$PidFile = Join-Path $Root ".uvicorn-$Port.pid"

$listeners = netstat -ano | Select-String ":$Port" | Select-String "LISTENING"
if ($listeners) {
    $pids = $listeners | ForEach-Object { ($_ -split "\s+")[-1] } | Sort-Object -Unique
    foreach ($pidText in $pids) {
        if ($pidText -match "^\d+$") {
            Stop-Process -Id ([int]$pidText) -Force -ErrorAction SilentlyContinue
        }
    }
    Start-Sleep -Seconds 1
}

Remove-Item -LiteralPath $PidFile -ErrorAction SilentlyContinue

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $Python
$psi.WorkingDirectory = $Root
$psi.Arguments = "-X utf8 -m uvicorn backend.main:app --host $HostName --port $Port"
$psi.UseShellExecute = $true
$psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden

$process = [System.Diagnostics.Process]::Start($psi)
$process.Id | Set-Content -LiteralPath $PidFile -Encoding ascii

Start-Sleep -Seconds 3

$health = "http://$HostName`:$Port/api/config"
try {
    $response = Invoke-WebRequest -Uri $health -UseBasicParsing -TimeoutSec 10
    "started pid=$($process.Id) port=$Port status=$($response.StatusCode) python=$Python"
} catch {
    "started pid=$($process.Id) port=$Port health_error=$($_.Exception.Message) python=$Python"
}
