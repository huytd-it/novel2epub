# build.ps1 - Build production (frontend -> app/webui)
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/build.ps1
#   powershell -ExecutionPolicy Bypass -File scripts/build.ps1 -SkipInstall

param(
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $Root

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "  $msg" -ForegroundColor Green }

Write-Step "Build production - frontend -> app/webui"

# Backend deps (de dam bao epub_builder / jinja2 co du)
$venvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    if (-not $SkipInstall) {
        Write-Step "pip install -r requirements.txt"
        & $venvPython -m pip install -r requirements.txt --quiet
        Write-Ok "Python deps OK"
    }
} else {
    Write-Host "  Canh bao: .venv chua co - build frontend van chay, nhung backend chua san sang" -ForegroundColor Yellow
}

# Frontend deps
if (-not (Test-Path (Join-Path $Root "frontend\node_modules"))) {
    Write-Step "npm install (frontend)"
    Push-Location (Join-Path $Root "frontend")
    npm install
    Pop-Location
}

Write-Step "Vite build"
Push-Location (Join-Path $Root "frontend")
npm run build
$code = $LASTEXITCODE
Pop-Location
if ($code -ne 0) { throw "npm run build failed ($code)" }

# Verify output
$index = Join-Path $Root "app\webui\index.html"
if (Test-Path $index) {
    Write-Ok "Build OK: $index"
    Get-ChildItem (Join-Path $Root "app\webui") | Format-Table Name, Length -AutoSize | Out-String | Write-Host
} else {
    throw "Build xong nhung khong thay app/webui/index.html"
}

Write-Host "`nChay thu production: powershell -ExecutionPolicy Bypass -File scripts/run.ps1" -ForegroundColor Yellow
