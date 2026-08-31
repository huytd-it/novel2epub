#Requires -Version 5.1
<#
.SYNOPSIS
    Build SPA production (frontend -> app/webui).
#>
param([switch]$SkipInstall)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Write-Step($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Write-Ok($m)   { Write-Host "  [OK] $m" -ForegroundColor Green }
function Write-Warn($m) { Write-Host "  [!] $m" -ForegroundColor Yellow }

Write-Step "Build SPA - frontend -> app/webui"
Write-Host "  Root: $Root" -ForegroundColor DarkGray

# -- Python check (best-effort) --
$pyCmd = $null
foreach ($c in @("python", "python3", "py")) {
    $f = Get-Command $c -ErrorAction SilentlyContinue
    if ($f) { $pyCmd = $c; break }
}
if ($pyCmd) {
    $ver = & $pyCmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
    Write-Ok "Python $ver ($pyCmd)"
    $venvPython = Join-Path $Root ".venv\Scripts\python.exe"
    if ((Test-Path $venvPython) -and (-not $SkipInstall)) {
        Write-Host "  pip install -r requirements.txt ..." -ForegroundColor DarkGray
        $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
        & $venvPython -m pip install -r requirements.txt --quiet 2>&1 | Out-Null
        $ErrorActionPreference = $old
        if ($LASTEXITCODE -eq 0) { Write-Ok "Python deps OK" } else { Write-Warn "pip install loi (bo qua)" }
    }
} else {
    Write-Warn "Khong tim thay Python - chi build frontend"
}

# -- Node --
$nodeOk = $false
try {
    $nodeVer = node --version 2>$null
    $npmVer = npm --version 2>$null
    if ($nodeVer) {
        $maj = [int]($nodeVer.Trim().TrimStart("v").Split(".")[0])
        if ($maj -lt 18) { Write-Warn "Node $nodeVer < 18 - khuyen nghi 18+" }
        else { Write-Ok "Node $nodeVer / npm $npmVer" }
        $nodeOk = $true
    }
} catch {}
if (-not $nodeOk) { throw "Can Node.js >=18 de build SPA (https://nodejs.org)" }

# -- Frontend deps --
$nodeModules = Join-Path $Root "frontend\node_modules"
$needInstall = -not (Test-Path $nodeModules)
if (-not $needInstall) {
    # package.json / package-lock.json moi hon node_modules -> deps da thay doi, can cai lai
    $lock = Join-Path $Root "frontend\package-lock.json"
    foreach ($f in @((Join-Path $Root "frontend\package.json"), $lock)) {
        $stamp = (Get-Item $f -ErrorAction SilentlyContinue).LastWriteTime
        $nmStamp = (Get-Item $nodeModules -ErrorAction SilentlyContinue).LastWriteTime
        if ($stamp -and $nmStamp -and $stamp -gt $nmStamp) { $needInstall = $true; break }
    }
}
if ($needInstall) {
    Write-Step "npm install (frontend)"
    Push-Location (Join-Path $Root "frontend")
    try {
        $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
        npm install 2>&1 | Write-Host
        $ok = ($LASTEXITCODE -eq 0); $ErrorActionPreference = $old
        if (-not $ok) { throw "npm install failed ($LASTEXITCODE)" }
    } finally { Pop-Location }
}

# -- Vite build --
Write-Step "Vite build"
Push-Location (Join-Path $Root "frontend")
try {
    $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    npm run build 2>&1 | Write-Host
    $ok = ($LASTEXITCODE -eq 0); $ErrorActionPreference = $old
    if (-not $ok) { throw "npm run build failed ($LASTEXITCODE)" }
} finally { Pop-Location }

# -- Verify --
$index = Join-Path $Root "app\webui\index.html"
if (Test-Path $index) {
    Write-Ok "Build OK: $index"
    Get-ChildItem (Join-Path $Root "app\webui") | Format-Table Name, Length -AutoSize | Out-String | Write-Host
} else {
    throw "Build xong nhung khong thay app/webui/index.html"
}
Write-Host "`nChay thu: powershell -ExecutionPolicy Bypass -File scripts/run.ps1" -ForegroundColor Yellow
Write-Host "Hoac build exe: powershell -ExecutionPolicy Bypass -File scripts/build-exe.ps1" -ForegroundColor Yellow
