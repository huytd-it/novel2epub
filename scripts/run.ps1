# run.ps1 - Chay production (build san -> uvicorn 8010)
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/run.ps1
#   powershell -ExecutionPolicy Bypass -File scripts/run.ps1 -Port 8010 -HostAddr 127.0.0.1
#   powershell -ExecutionPolicy Bypass -File scripts/run.ps1 -NoBuild

param(
    [int]$Port = 8010,
    [string]$HostAddr = "127.0.0.1",
    [switch]$NoBuild,
    [switch]$Reload,
    [string]$DbPath = ""
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $Root

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "  $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  $msg" -ForegroundColor Yellow }

$venvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Warn ".venv chua co - tao moi + pip install"
    python -m venv .venv
    $venvPython = Join-Path $Root ".venv\Scripts\python.exe"
    & $venvPython -m pip install -r requirements.txt
}

# DB check
$dbFile = if ($DbPath) { $DbPath } elseif ($env:NOVEL2EPUB_DB) { $env:NOVEL2EPUB_DB } else { Join-Path $Root "novel2epub.db" }
if (-not (Test-Path $dbFile)) {
    Write-Step "DB chua co - init $dbFile"
    & $venvPython scripts/init_db.py --db $dbFile
} else {
    Write-Ok "DB: $dbFile"
}

# Build check
$built = Test-Path (Join-Path $Root "app\webui\index.html")
if (-not $built -and -not $NoBuild) {
    Write-Warn "Chua co app/webui/index.html - build frontend truoc..."
    Push-Location (Join-Path $Root "frontend")
    if (-not (Test-Path "node_modules")) { npm install }
    npm run build
    Pop-Location
} elseif (-not $built) {
    Write-Warn "Chua build frontend - SPA /app se 404, Jinja2 / van chay"
} else {
    Write-Ok "SPA bundle: app/webui/index.html OK"
}

Write-Step "Khoi dong production - http://${HostAddr}:$Port"
Write-Host "  SPA  : http://${HostAddr}:$Port/app/" -ForegroundColor White
Write-Host "  Jinja: http://${HostAddr}:$Port/" -ForegroundColor White
Write-Host "  Docs : http://${HostAddr}:$Port/docs" -ForegroundColor DarkGray

$uvArgs = @("-m", "uvicorn", "app.main:app", "--host", $HostAddr, "--port", "$Port")
if ($Reload) { $uvArgs += "--reload" }

& $venvPython @uvArgs
