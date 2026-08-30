# dev.ps1 - Khởi động môi trường DEV (backend 8011 + frontend Vite 5183)
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/dev.ps1
#   powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 -SkipInstall
#   powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 -Port 8011

param(
    [int]$Port = 8011,
    [switch]$SkipInstall,
    [string]$DbPath = ""
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $Root

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "  $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  $msg" -ForegroundColor Yellow }

# 1. Python venv check
Write-Step "Kiem tra Python & venv"
$venvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Warn ".venv chua co - tao moi..."
    python -m venv .venv
    $venvPython = Join-Path $Root ".venv\Scripts\python.exe"
}
& $venvPython --version | Out-Null
Write-Ok "Python: $(& $venvPython --version 2>&1)"

# 2. Install deps (unless --SkipInstall)
if (-not $SkipInstall) {
    Write-Step "Cai dat dependencies Python"
    & $venvPython -m pip install --upgrade pip --quiet
    & $venvPython -m pip install -r requirements.txt
    # Scrapling browser deps (best-effort, ko fail neu offline)
    try { & $venvPython -m scrapling install 2>&1 | Out-Null; Write-Ok "scrapling install OK" } catch { Write-Warn "scrapling install skip: $_" }
} else {
    Write-Warn "SkipInstall - bo qua pip install"
}

# 3. DB init if missing
$dbFile = if ($DbPath) { $DbPath } elseif ($env:NOVEL2EPUB_DB) { $env:NOVEL2EPUB_DB } else { Join-Path $Root "novel2epub.db" }
if (-not (Test-Path $dbFile)) {
    Write-Step "DB chua co - khoi tao $dbFile"
    & $venvPython scripts/init_db.py --db $dbFile
} else {
    Write-Ok "DB da co: $dbFile"
}

# 4. Frontend deps
Write-Step "Kiem tra frontend deps"
if (-not (Test-Path (Join-Path $Root "frontend\node_modules"))) {
    if (-not $SkipInstall) {
        Write-Host "  npm install ..." -ForegroundColor Yellow
        Push-Location (Join-Path $Root "frontend")
        npm install
        Pop-Location
    } else {
        Write-Warn "frontend/node_modules thieu nhung SkipInstall - vite co the loi"
    }
} else {
    Write-Ok "frontend/node_modules OK"
}

# 5. Start backend + frontend
Write-Step "Khoi dong DEV - backend :$Port + Vite :5183"
Write-Host "  Backend : http://127.0.0.1:$Port  (proxy target cho Vite)" -ForegroundColor White
Write-Host "  Vite    : http://localhost:5183/app/" -ForegroundColor White
Write-Host "  Jinja2  : http://127.0.0.1:$Port/  (UI cu, van chay song song)" -ForegroundColor DarkGray
Write-Host "  Bam Ctrl+C de dung (can dong ca 2 cua so neu mo rieng)" -ForegroundColor Yellow

# Chay backend background + vite foreground (de Ctrl+C dong vite thi kill backend)
$backendJob = Start-Process -FilePath $venvPython -ArgumentList "-m","uvicorn","app.main:app","--reload","--port","$Port" -WorkingDirectory $Root -PassThru
Write-Ok "Backend PID $($backendJob.Id) - doi 2s cho reload..."
Start-Sleep -Seconds 2

try {
    Push-Location (Join-Path $Root "frontend")
    # Vite se proxy /api -> 127.0.0.1:$Port (xem vite.config.ts -> N2E_DEV_API_TARGET)
    if ($Port -ne 8011) { $env:N2E_DEV_API_TARGET = "http://127.0.0.1:$Port" }
    npm run dev
} finally {
    Pop-Location
    if (-not $backendJob.HasExited) {
        Write-Host "`nDung backend PID $($backendJob.Id)..." -ForegroundColor Yellow
        Stop-Process -Id $backendJob.Id -Force -ErrorAction SilentlyContinue
    }
}
