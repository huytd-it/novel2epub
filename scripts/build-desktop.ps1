# build-desktop.ps1 - Build Tauri desktop (vite + tauri build)
# Tu dong kiem tra moi truong, ho tro -Debug va -Clean
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/build-desktop.ps1
#   powershell -ExecutionPolicy Bypass -File scripts/build-desktop.ps1 -Debug
#   powershell -ExecutionPolicy Bypass -File scripts/build-desktop.ps1 -Clean

param(
    [switch]$Debug,
    [switch]$Clean,
    [switch]$SkipInstall
)

$ErrorActionPreference = "Continue"
$Root = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $Root

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  [!] $msg" -ForegroundColor Yellow }

$mode = if($Debug){ "debug" } else { "release" }
Write-Step "Build desktop Tauri ($mode)"

# -- Clean
if($Clean){
    Write-Step "Clean"
    Remove-Item -Recurse -Force (Join-Path $Root "frontend\dist") -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force (Join-Path $Root "frontend\src-tauri\target") -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force (Join-Path $Root "app\webui") -ErrorAction SilentlyContinue
    Write-Ok "Da clean"
    if(-not $Debug){ # Clean only -> dung
        Write-Host "Clean xong." -ForegroundColor Green
        return
    }
}

# -- Check Rust
try{ $rv=rustc --version 2>$null; if($rv){ Write-Ok "Rust $rv" } else { Write-Warn "Chua cai Rust (https://rustup.rs) - tauri build se loi" } }catch{ Write-Warn "Chua cai Rust" }

# -- Check Node/Python
$nodeOk=$false; try{ $nv=node --version 2>$null; if($nv){ Write-Ok "Node $nv"; $nodeOk=$true } }catch{}
if(-not $nodeOk){ throw "Can Node.js" }
if(-not (Test-Path (Join-Path $Root "frontend\node_modules")) -and -not $SkipInstall){
    Write-Step "npm install"
    Push-Location (Join-Path $Root "frontend"); npm install 2>&1 | Write-Host; Pop-Location
}

# -- Typecheck
Write-Step "Typecheck"
Push-Location (Join-Path $Root "frontend")
$oldEA=$ErrorActionPreference; $ErrorActionPreference="Continue"
npm run typecheck 2>&1 | Write-Host
if($LASTEXITCODE -ne 0){ Write-Warn "typecheck co loi (van tiep tuc)" }
$ErrorActionPreference=$oldEA
Pop-Location

# -- Vite build (tauri mode)
Write-Step "Vite build --mode tauri"
Push-Location (Join-Path $Root "frontend")
$oldEA=$ErrorActionPreference; $ErrorActionPreference="Continue"
if($Debug){ npm run build 2>&1 | Write-Host } else { npm run build 2>&1 | Write-Host }
# build:tauri = tsc -b && vite build --mode tauri
npx tsc -b 2>&1 | Write-Host
npx vite build --mode tauri 2>&1 | Write-Host
$ErrorActionPreference=$oldEA
Pop-Location

# -- Tauri build
Write-Step "Tauri build ($mode)"
Push-Location (Join-Path $Root "frontend")
$oldEA=$ErrorActionPreference; $ErrorActionPreference="Continue"
if($Debug){
    npx tauri build --debug 2>&1 | Write-Host
} else {
    npx tauri build 2>&1 | Write-Host
}
$code=$LASTEXITCODE; $ErrorActionPreference=$oldEA
Pop-Location
if($code -ne 0){ throw "tauri build failed ($code)" }

# -- Result
$targetDir = Join-Path $Root "frontend\src-tauri\target\release\bundle"
if(Test-Path $targetDir){
    Get-ChildItem $targetDir -Recurse -Filter "*.exe" -ErrorAction SilentlyContinue | Select-Object -First 5 | ForEach-Object { Write-Ok "$($_.FullName) ($([math]::Round($_.Length/1MB,1)) MB)" }
    Get-ChildItem $targetDir -Recurse -Filter "*.msi" -ErrorAction SilentlyContinue | Select-Object -First 3 | ForEach-Object { Write-Ok "MSI: $($_.Name)" }
}
Write-Host "`nHoan tat build desktop ($mode)." -ForegroundColor Green
Write-Host "Chay thu: npm run tauri:dev  (tu frontend)" -ForegroundColor Yellow
