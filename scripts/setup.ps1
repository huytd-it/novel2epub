# setup.ps1 - Khoi tao moi truong dev lan dau (one-shot)
# - Kiem tra Python >=3.10, Node >=18, tao .venv, cai deps, tao .env random port, init DB
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/setup.ps1
#   powershell -ExecutionPolicy Bypass -File scripts/setup.ps1 -SkipInstall

param(
    [switch]$SkipInstall,
    [string]$EnvFile = ".env"
)

$ErrorActionPreference = "Continue"
$Root = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $Root

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  [!] $msg" -ForegroundColor Yellow }

Write-Step "Setup moi truong novel2epub"

# -- Python
$pyCmd = $null; foreach($c in @("python","python3","py")){ $f=Get-Command $c -ErrorAction SilentlyContinue; if($f){$pyCmd=$c;break} }
if(-not $pyCmd){ throw "Khong tim thay Python >=3.10 (https://python.org)" }
$ver = & $pyCmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" 2>$null
$parts=$ver.Trim().Split("."); if([int]$parts[0] -lt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -lt 10)){ throw "Can Python >=3.10, hien tai $ver" }
Write-Ok "Python $ver ($pyCmd)"

# -- Node
$nodeOk=$false; try{ $nv=node --version 2>$null; $npmv=npm --version 2>$null; if($nv){ $maj=[int]$nv.Trim().TrimStart("v").Split(".")[0]; if($maj -lt 18){Write-Warn "Node $nv <18"} else{Write-Ok "Node $nv / npm $npmv"}; $nodeOk=$true } }catch{}
if(-not $nodeOk){ Write-Warn "Khong tim thay Node.js - frontend se thieu (https://nodejs.org)" }

# -- .venv
$venvPython = Join-Path $Root ".venv\Scripts\python.exe"
if(-not (Test-Path $venvPython)){
    Write-Step "Tao .venv"
    & $pyCmd -m venv .venv
    $venvPython = Join-Path $Root ".venv\Scripts\python.exe"
    Write-Ok "Da tao .venv"
} else { Write-Ok "venv: $venvPython" }

# -- pip + deps
if(-not $SkipInstall){
    Write-Step "Cap nhat pip va cai deps Python"
    & $venvPython -m pip install --upgrade pip setuptools wheel -q 2>&1 | Out-Null
    & $venvPython -m pip install -r requirements.txt --quiet 2>&1 | Out-Null
    if($LASTEXITCODE -eq 0){ Write-Ok "requirements.txt OK" } else { Write-Warn "pip install loi" }
    $oldEA=$ErrorActionPreference; $ErrorActionPreference="Continue"
    & $venvPython -m pip install -q pystray pillow 2>&1 | Out-Null
    $ErrorActionPreference=$oldEA
} else { Write-Warn "SkipInstall" }

# -- frontend deps
if(-not (Test-Path (Join-Path $Root "frontend\node_modules"))){
    Write-Step "npm install (frontend)"
    Push-Location (Join-Path $Root "frontend")
    $oldEA=$ErrorActionPreference; $ErrorActionPreference="Continue"
    npm install 2>&1 | Write-Host
    $ErrorActionPreference=$oldEA
    Pop-Location
} else { Write-Ok "frontend/node_modules OK" }

# -- .env random port
$envPath = Join-Path $Root $EnvFile
if(-not (Test-Path $envPath)){
    Write-Step "Tao .env voi port ngau nhien"
    $py = if(Test-Path $venvPython){$venvPython}else{$pyCmd}
    $code="import socket,random; s=socket.socket(s.AF_INET,s.SOCK_STREAM); s.bind(('127.0.0.1',0)); print(s.getsockname()[1])"
    try{ $port=[int](& $py -c $code 2>$null).Trim() }catch{ $port=Get-Random -Minimum 8000 -Maximum 9500 }
    if(-not $port -or $port -eq 0){ $port=Get-Random -Minimum 8000 -Maximum 9500 }
    "N2E_TRAY_PORT=$port`nN2E_TRAY_HOST=127.0.0.1`n" | Set-Content $envPath -Encoding utf8
    Write-Ok "Da tao $EnvFile : PORT=$port"
} else {
    Write-Ok ".env da co: $envPath"
    Get-Content $envPath | Select-Object -First 5 | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
}

# -- DB
$dbFile = if($env:NOVEL2EPUB_DB){$env:NOVEL2EPUB_DB} else{ Join-Path $Root "novel2epub.db" }
if(-not (Test-Path $dbFile)){
    Write-Step "Init DB $dbFile"
    & $venvPython scripts/init_db.py --db $dbFile
    Write-Ok "DB OK"
} else { Write-Ok "DB: $dbFile ($([math]::Round((Get-Item $dbFile).Length/1MB,1)) MB)" }

# -- Verify frontend build
if(-not (Test-Path (Join-Path $Root "app\webui\index.html"))){
    Write-Warn "Chua co app/webui/index.html - chay: powershell -ExecutionPolicy Bypass -File scripts/build.ps1"
} else { Write-Ok "SPA bundle OK" }

Write-Host "`nHoan tat setup. Chay dev: powershell -ExecutionPolicy Bypass -File scripts/dev.ps1" -ForegroundColor Green
Write-Host "Hoac build exe: powershell -ExecutionPolicy Bypass -File scripts/build-exe.ps1" -ForegroundColor Green
