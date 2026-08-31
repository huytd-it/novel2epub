#Requires -Version 5.1
<#
.SYNOPSIS
    Khoi tao moi truong dev lan dau (one-shot, idempotent).
.DESCRIPTION
    - Kiem tra Python >=3.10, Node >=18
    - Tao .venv, cai deps Python + frontend
    - Tao .env voi port ngau nhien + init DB tu novel2epub.example.yaml
    - Verify SPA bundle
#>
param(
    [switch]$SkipInstall,
    [string]$EnvFile = ".env"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  novel2epub - Setup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

function Write-Step($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Write-Ok($m)   { Write-Host "  [OK] $m" -ForegroundColor Green }
function Write-Warn($m) { Write-Host "  [!] $m" -ForegroundColor Yellow }

Write-Step "Kiem tra Python"

$pyCmd = $null
foreach ($c in @("python", "python3", "py")) {
    $f = Get-Command $c -ErrorAction SilentlyContinue
    if ($f) { $pyCmd = $c; break }
}
if (-not $pyCmd) { throw "Khong tim thay Python >=3.10 (https://python.org)" }

$verRaw = & $pyCmd --version 2>&1 | Out-String
$ver = $verRaw.Trim() -replace '^Python\s+', ''
$parts = $ver.Split(".")
if ($parts.Count -lt 2 -or [int]$parts[0] -lt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -lt 10)) {
    throw "Can Python >=3.10, hien tai $ver"
}
Write-Ok "Python $ver ($pyCmd)"

Write-Step "Kiem tra Node"
$nodeOk = $false
try {
    $nv = node --version 2>$null
    $npmv = npm --version 2>$null
    if ($nv) {
        $maj = [int]$nv.Trim().TrimStart("v").Split(".")[0]
        if ($maj -lt 18) { Write-Warn "Node $nv <18 (khuyen nghi 18+)" }
        else { Write-Ok "Node $nv / npm $npmv" }
        $nodeOk = $true
    }
} catch {}
if (-not $nodeOk) { Write-Warn "Khong tim thay Node.js - frontend se thieu (https://nodejs.org)" }

Write-Step "Tao .venv"
$venvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "  Tao .venv ..." -ForegroundColor DarkGray
    & $pyCmd -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Tao .venv that bai" }
    if (-not (Test-Path $venvPython)) { throw "Tao .venv that bai (khong thay $venvPython)" }
    Write-Ok "Da tao .venv"
} else {
    Write-Ok "venv: $venvPython"
}

if (-not $SkipInstall) {
    Write-Host "`n[1/3] Cai deps Python ..." -ForegroundColor Yellow
    & $venvPython -m pip install --upgrade pip setuptools wheel --quiet
    if ($LASTEXITCODE -ne 0) { Write-Warn "pip upgrade loi (bo qua)" } else { Write-Ok "pip/wheel OK" }

    & $venvPython -m pip install -r requirements.txt --quiet
    if ($LASTEXITCODE -ne 0) { Write-Warn "pip install loi (kiem tra output)" } else { Write-Ok "requirements.txt OK" }

    & $venvPython -m pip install -q pystray pillow --quiet
    if ($LASTEXITCODE -ne 0) { Write-Warn "pystray/pillow loi (bo qua)" } else { Write-Ok "pystray/pillow OK" }
} else {
    Write-Warn "SkipInstall - bo qua pip install"
}

if (-not (Test-Path (Join-Path $Root "frontend\node_modules"))) {
    if ($SkipInstall) {
        Write-Warn "Thieu node_modules nhung SkipInstall - chay lai khong co --SkipInstall de cai"
    } else {
        Write-Host "`n[2/3] npm install (frontend) ..." -ForegroundColor Yellow
        Push-Location (Join-Path $Root "frontend")
        try {
            npm install
            if ($LASTEXITCODE -ne 0) { throw "npm install failed ($LASTEXITCODE)" }
            Write-Ok "npm install OK"
        } finally { Pop-Location }
    }
} else {
    Write-Ok "frontend/node_modules OK"
}

$envPath = Join-Path $Root $EnvFile
if (-not (Test-Path $envPath)) {
    Write-Host "`n[3/3] Tao .env ..." -ForegroundColor Yellow
    $pyForPort = if (Test-Path $venvPython) { $venvPython } else { $pyCmd }
    $code = "import socket; s=socket.socket(s.AF_INET,s.SOCK_STREAM); s.bind(('127.0.0.1',0)); print(s.getsockname()[1])"
    try { $port = [int](& $pyForPort -c $code 2>$null).Trim() } catch { $port = 0 }
    if (-not $port -or $port -eq 0) { $port = Get-Random -Minimum 8000 -Maximum 9500 }
    # utf8NoBOM de tranh BOM lam loi parser .env / tauri
    [System.IO.File]::WriteAllText($envPath, "N2E_TRAY_PORT=$port`nN2E_TRAY_HOST=127.0.0.1`n", [System.Text.UTF8Encoding]::new($false))
    Write-Ok "Da tao $EnvFile : PORT=$port"
} else {
    Write-Ok ".env da co: $envPath"
    Get-Content $envPath | Select-Object -First 5 | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
}

$dbFile = if ($env:NOVEL2EPUB_DB) { $env:NOVEL2EPUB_DB } else { Join-Path $Root "novel2epub.db" }
if (-not (Test-Path $dbFile)) {
    Write-Step "Init DB $dbFile"
    & $venvPython scripts/init_db.py --db $dbFile
    if ($LASTEXITCODE -ne 0) { Write-Warn "init_db loi - kiem tra novel2epub.example.yaml" } else { Write-Ok "DB OK" }
} else {
    $sz = [math]::Round((Get-Item $dbFile).Length / 1MB, 1)
    Write-Ok "DB: $dbFile ($sz MB)"
}

if (-not (Test-Path (Join-Path $Root "app\webui\index.html"))) {
    Write-Warn "Chua co app/webui/index.html - chay: powershell -ExecutionPolicy Bypass -File scripts/build.ps1"
} else {
    Write-Ok "SPA bundle OK"
}

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  Hoan tat setup." -ForegroundColor Green
Write-Host "  Dev : powershell -ExecutionPolicy Bypass -File scripts/dev.ps1" -ForegroundColor White
Write-Host "  Run : powershell -ExecutionPolicy Bypass -File scripts/run.ps1" -ForegroundColor White
Write-Host "  Exe : powershell -ExecutionPolicy Bypass -File scripts/build-exe.ps1" -ForegroundColor White
Write-Host "========================================" -ForegroundColor Cyan
