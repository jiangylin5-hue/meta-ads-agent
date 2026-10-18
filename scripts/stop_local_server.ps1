param(
    [int]$Port = 8010
)

$ErrorActionPreference = "SilentlyContinue"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$PidFile = Join-Path $Root ".uvicorn-$Port.pid"

if (Test-Path $PidFile) {
    $pidText = Get-Content -LiteralPath $PidFile -Raw
    if ($pidText -match "^\s*(\d+)\s*$") {
        Stop-Process -Id ([int]$Matches[1]) -Force
    }
    Remove-Item -LiteralPath $PidFile -Force
}

$listeners = netstat -ano | Select-String ":$Port" | Select-String "LISTENING"
if ($listeners) {
    $pids = $listeners | ForEach-Object { ($_ -split "\s+")[-1] } | Sort-Object -Unique
    foreach ($pidText in $pids) {
        if ($pidText -match "^\d+$") {
            Stop-Process -Id ([int]$pidText) -Force
        }
    }
}

"stopped port=$Port"
