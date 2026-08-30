# install.ps1 - Cai dat toan bo dependencies (Python + Node + Scrapling browser)
# Tu dong kiem tra moi truong, tao .venv neu thieu
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/install.ps1
#   powershell -ExecutionPolicy Bypass -File scripts/install.ps1 -WithBrowsers

param(
    [switch]$WithBrowsers,
    [switch]$Upgrade
)

$ErrorActionPreference = "Continue"
$Root = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $Root

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  [!] $msg" -ForegroundColor Yellow }

Write-Step "Install all dependencies"

# -- Python
$pyCmd=$null; foreach($c in @("python","python3","py")){ $f=Get-Command $c -ErrorAction SilentlyContinue; if($f){$pyCmd=$c;break} }
if(-not $pyCmd){ throw "Khong tim thay Python" }
$ver = & $pyCmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
Write-Ok "Python $ver ($pyCmd)"

$venvPython = Join-Path $Root ".venv\Scripts\python.exe"
if(-not (Test-Path $venvPython)){
    Write-Step "Tao .venv"
    & $pyCmd -m venv .venv
    $venvPython = Join-Path $Root ".venv\Scripts\python.exe"
    Write-Ok "Da tao .venv"
}

Write-Step "pip install"
if($Upgrade){ & $venvPython -m pip install --upgrade pip setuptools wheel 2>&1 | Out-Null }
$oldEA=$ErrorActionPreference; $ErrorActionPreference="Continue"
& $venvPython -m pip install -r requirements.txt 2>&1 | Write-Host
if($LASTEXITCODE -ne 0){ Write-Warn "pip install co loi" } else { Write-Ok "requirements.txt OK" }
& $venvPython -m pip install pystray pillow pyinstaller --quiet 2>&1 | Out-Null
Write-Ok "pystray/pillow/pyinstaller OK"
$ErrorActionPreference=$oldEA

if($WithBrowsers){
    Write-Step "Scrapling browser install"
    & $venvPython -m scrapling install 2>&1 | Write-Host
}

# -- Node
$nodeOk=$false; try{ $nv=node --version 2>$null; if($nv){ Write-Ok "Node $nv / npm $(npm --version 2>$null)"; $nodeOk=$true } }catch{}
if(-not $nodeOk){ Write-Warn "Khong tim thay Node.js" } else {
    Write-Step "npm install (frontend)"
    if(-not (Test-Path (Join-Path $Root "frontend\node_modules"))){
        Push-Location (Join-Path $Root "frontend")
        npm install 2>&1 | Write-Host
        Pop-Location
    } else { Write-Ok "frontend/node_modules OK" }
    # Tauri CLI check
    try{ $tv=npx tauri --version 2>$null; if($tv){ Write-Ok "Tauri $tv" } }catch{ Write-Warn "Tauri CLI chua cai (npm i -D @tauri-apps/cli)" }
}

Write-Host "`nHoan tat. Chay: powershell -ExecutionPolicy Bypass -File scripts/dev.ps1" -ForegroundColor Green
