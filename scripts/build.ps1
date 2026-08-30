# build.ps1 - Build SPA production (frontend -> app/webui) - SPA only
# Tu dong kiem tra moi truong (Python, Node, venv) va cai dat
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/build.ps1
#   powershell -ExecutionPolicy Bypass -File scripts/build.ps1 -SkipInstall

param(
    [switch]$SkipInstall
)

$ErrorActionPreference = "Continue"
$Root = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $Root

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  [!] $msg" -ForegroundColor Yellow }

Write-Step "Build SPA - frontend -> app/webui"

# -- Python check (de dam bao epub_builder co du)
$pyCmd = $null
foreach ($c in @("python","python3","py")) { $f=Get-Command $c -ErrorAction SilentlyContinue; if($f){$pyCmd=$c;break} }
if ($pyCmd) {
    $ver = & $pyCmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
    Write-Ok "Python $ver ($pyCmd)"
    $venvPython = Join-Path $Root ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        if (-not $SkipInstall) {
            Write-Step "pip install -r requirements.txt"
            $oldEA=$ErrorActionPreference; $ErrorActionPreference="Continue"
            & $venvPython -m pip install -r requirements.txt --quiet 2>&1 | Out-Null
            $ErrorActionPreference=$oldEA
            if ($LASTEXITCODE -eq 0) { Write-Ok "Python deps OK" } else { Write-Warn "pip install co loi (bo qua)" }
        }
    } else {
        Write-Warn ".venv chua co - build frontend van chay, backend chua san sang"
    }
} else {
    Write-Warn "Khong tim thay Python - chi build frontend"
}

# -- Node check
$nodeOk = $false
try {
    $nodeVer = node --version 2>$null; $npmVer = npm --version 2>$null
    if ($nodeVer) {
        $maj = [int]($nodeVer.Trim().TrimStart("v").Split(".")[0])
        if ($maj -lt 18) { Write-Warn "Node $nodeVer < 18 - khuyen nghi 18+" } else { Write-Ok "Node $nodeVer / npm $npmVer" }
        $nodeOk = $true
    }
} catch {}
if (-not $nodeOk) { throw "Can Node.js >=18 de build SPA (cai tu https://nodejs.org)" }

# -- Frontend deps
if (-not (Test-Path (Join-Path $Root "frontend\node_modules"))) {
    Write-Step "npm install (frontend)"
    Push-Location (Join-Path $Root "frontend")
    $oldEA=$ErrorActionPreference; $ErrorActionPreference="Continue"
    npm install 2>&1 | Write-Host
    $code=$LASTEXITCODE; $ErrorActionPreference=$oldEA
    Pop-Location
    if ($code -ne 0) { throw "npm install failed ($code)" }
}

Write-Step "Vite build"
Push-Location (Join-Path $Root "frontend")
$oldEA=$ErrorActionPreference; $ErrorActionPreference="Continue"
npm run build 2>&1 | Write-Host
$code=$LASTEXITCODE; $ErrorActionPreference=$oldEA
Pop-Location
if ($code -ne 0) { throw "npm run build failed ($code)" }

# Verify
$index = Join-Path $Root "app\webui\index.html"
if (Test-Path $index) {
    Write-Ok "Build OK: $index"
    Get-ChildItem (Join-Path $Root "app\webui") | Format-Table Name, Length -AutoSize | Out-String | Write-Host
} else {
    throw "Build xong nhung khong thay app/webui/index.html"
}
Write-Host "`nChay thu: powershell -ExecutionPolicy Bypass -File scripts/run.ps1" -ForegroundColor Yellow
Write-Host "Hoac build exe: powershell -ExecutionPolicy Bypass -File scripts/build-exe.ps1" -ForegroundColor Yellow
