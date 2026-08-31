#Requires -Version 5.1
<#
.SYNOPSIS
    Cai dat toan bo dependencies (Python + Node + Scrapling browser).
#>
param(
    [switch]$WithBrowsers,
    [switch]$Upgrade
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Write-Step($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Write-Ok($m)   { Write-Host "  [OK] $m" -ForegroundColor Green }
function Write-Warn($m) { Write-Host "  [!] $m" -ForegroundColor Yellow }

Write-Step "Install all dependencies"
Write-Host "  Root: $Root" -ForegroundColor DarkGray

# -- Python --
$pyCmd = $null
foreach ($c in @("python", "python3", "py")) {
    $f = Get-Command $c -ErrorAction SilentlyContinue
    if ($f) { $pyCmd = $c; break }
}
if (-not $pyCmd) { throw "Khong tim thay Python" }
$ver = & $pyCmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
Write-Ok "Python $ver ($pyCmd)"

$venvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "  Tao .venv ..." -ForegroundColor DarkGray
    & $pyCmd -m venv .venv
    if (-not (Test-Path $venvPython)) { throw "Tao .venv that bai" }
    Write-Ok "Da tao .venv"
} else {
    Write-Ok "venv: $venvPython"
}

# -- pip --
Write-Host "`n[1/2] pip install ..." -ForegroundColor Yellow
if ($Upgrade) {
    Write-Host "  pip upgrade ..." -ForegroundColor DarkGray
    $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    & $venvPython -m pip install --upgrade pip setuptools wheel 2>&1 | Out-Null
    $ErrorActionPreference = $old
}
$old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
& $venvPython -m pip install -r requirements.txt 2>&1 | Write-Host
if ($LASTEXITCODE -ne 0) { Write-Warn "pip install co loi" } else { Write-Ok "requirements.txt OK" }
$ErrorActionPreference = $old

$old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
& $venvPython -m pip install pystray pillow pyinstaller --quiet 2>&1 | Out-Null
$ErrorActionPreference = $old
Write-Ok "pystray/pillow/pyinstaller OK"

if ($WithBrowsers) {
    Write-Step "Scrapling browser install"
    $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    & $venvPython -m scrapling install 2>&1 | Write-Host
    $ErrorActionPreference = $old
}

# -- Node --
$nodeOk = $false
try {
    $nv = node --version 2>$null
    if ($nv) { Write-Ok "Node $nv / npm $(npm --version 2>$null)"; $nodeOk = $true }
} catch {}
if (-not $nodeOk) {
    Write-Warn "Khong tim thay Node.js"
} else {
    if (-not (Test-Path (Join-Path $Root "frontend\node_modules"))) {
        Write-Host "`n[2/2] npm install (frontend) ..." -ForegroundColor Yellow
        Push-Location (Join-Path $Root "frontend")
        try {
            $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
            npm install 2>&1 | Write-Host
            $ok = ($LASTEXITCODE -eq 0); $ErrorActionPreference = $old
            if (-not $ok) { throw "npm install failed ($LASTEXITCODE)" }
        } finally { Pop-Location }
    } else {
        Write-Ok "frontend/node_modules OK"
    }
    try {
        $tv = npx tauri --version 2>$null
        if ($tv) { Write-Ok "Tauri $tv" }
        else { Write-Warn "Tauri CLI chua cai (npm i -D @tauri-apps/cli trong frontend/)" }
    } catch { Write-Warn "Tauri CLI chua cai" }
}

Write-Host "`nHoan tat. Chay: powershell -ExecutionPolicy Bypass -File scripts/dev.ps1" -ForegroundColor Green
