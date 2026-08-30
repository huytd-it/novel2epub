# build-exe.ps1 - Đóng gói novel2epub thành exe chạy nền (tray)
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/build-exe.ps1
#   powershell -ExecutionPolicy Bypass -File scripts/build-exe.ps1 -NoWindow   # ẩn console
#   powershell -ExecutionPolicy Bypass -File scripts/build-exe.ps1 -Port 8010 -OneFile
#
# Kết quả: dist/novel2epub-tray.exe  (one-file) hoặc dist/novel2epub-tray/ (onedir)

param(
    [int]$Port = 8010,
    [string]$HostAddr = "127.0.0.1",
    [switch]$OneFile = $true,
    [switch]$NoWindow = $true,
    [switch]$SkipBuild,          # bỏ qua vite build
    [switch]$SkipInstall,
    [string]$IconPath = ""
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $Root

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "  $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  $msg" -ForegroundColor Yellow }

# ── 0. Chuẩn bị venv & deps ────────────────────────────────────────

$venvPython = Join-Path $Root ".venv\Scripts\python.exe"
$venvPip    = Join-Path $Root ".venv\Scripts\pip.exe"
if (-not (Test-Path $venvPython)) {
    Write-Warn ".venv chưa có - tạo mới"
    python -m venv .venv
}
if (-not $SkipInstall) {
    Write-Step "Cài deps Python"
    & $venvPython -m pip install -q -r requirements.txt
    # Deps riêng cho tray exe
    & $venvPython -m pip install -q pystray pillow pyinstaller
    Write-Ok "Deps OK (pystray/pillow/pyinstaller)"
} else {
    # vẫn đảm bảo pyinstaller có
    & $venvPython -m pip show pyinstaller 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        & $venvPython -m pip install -q pystray pillow pyinstaller
    }
}

# ── 1. Build SPA (để exe phục vụ /app) ─────────────────────────────

$built = Test-Path (Join-Path $Root "app\webui\index.html")
if (-not $built -and -not $SkipBuild) {
    Write-Step "Build SPA -> app/webui"
    Push-Location (Join-Path $Root "frontend")
    if (-not (Test-Path "node_modules")) { npm install }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "vite build failed" }
    Pop-Location
    $built = Test-Path (Join-Path $Root "app\webui\index.html")
} elseif ($built) {
    Write-Ok "SPA bundle sẵn: app/webui/index.html"
} else {
    Write-Warn "Bỏ qua build SPA - /app sẽ 404, Jinja2 vẫn chạy"
}

# ── 2. Icon ─────────────────────────────────────────────────────────

if (-not $IconPath) {
    $cands = @(
        (Join-Path $Root "frontend\src-tauri\icons\icon.ico"),
        (Join-Path $Root "desktop\icon.ico"),
        (Join-Path $Root "app\webui\icon.png")
    )
    foreach ($c in $cands) { if (Test-Path $c) { $IconPath = $c; break } }
}
if ($IconPath -and (Test-Path $IconPath)) {
    Write-Ok "Icon: $IconPath"
} else {
    Write-Warn "Không tìm thấy icon.ico - sẽ dùng icon mặc định"
    $IconPath = ""
}

# ── 3. PyInstaller ──────────────────────────────────────────────────

Write-Step "Đóng gói exe với PyInstaller"

# Dọn dist cũ
if (Test-Path (Join-Path $Root "dist"))  { Remove-Item -Recurse -Force (Join-Path $Root "dist") }
if (Test-Path (Join-Path $Root "build")) { Remove-Item -Recurse -Force (Join-Path $Root "build") }

$exeName = "novel2epub-tray"
$entry   = Join-Path $Root "desktop\tray_app.py"

# Hidden imports: FastAPI app + novel2epub domain + templating
$hidden = @(
    "app.main", "app.deps", "app.job", "app.queue", "app.scheduler",
    "app.logging_config",
    "app.routes.ebooks", "app.routes.chapters", "app.routes.characters",
    "app.routes.glossary", "app.routes.idioms", "app.routes.jobs",
    "app.routes.library", "app.routes.notes", "app.routes.opds",
    "app.routes.reader", "app.routes.settings", "app.routes.sources",
    "app.routes.storage", "app.routes.tailscale", "app.routes.webui",
    "app.routes.wireguard", "app.routes.dashboard", "app.routes.automation",
    "novel2epub.config", "novel2epub.db", "novel2epub.storage",
    "novel2epub.crawler", "novel2epub.pipeline", "novel2epub.translator",
    "novel2epub.epub_builder", "novel2epub.sources",
    "uvicorn.logging", "uvicorn.loops", "uvicorn.loops.auto",
    "uvicorn.protocols", "uvicorn.protocols.http", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan", "uvicorn.lifespan.on",
    "jinja2.ext", "yaml", "PIL", "pystray"
)

$addData = @()
# Bundle SPA + icons + config seed (chi them neu ton tai)
if ($built) {
    $addData += "app/webui;app/webui"
}
if (Test-Path (Join-Path $Root "frontend\src-tauri\icons")) {
    $addData += "frontend/src-tauri/icons;frontend/src-tauri/icons"
}
# app/templates khong con dung (legacy Jinja2), bo qua neu khong co
if (Test-Path (Join-Path $Root "app\templates")) {
    $addData += "app/templates;app/templates"
}
if (Test-Path (Join-Path $Root "novel2epub.example.yaml")) {
    $addData += "novel2epub.example.yaml;."
}
if (Test-Path (Join-Path $Root "sources.yaml")) {
    $addData += "sources.yaml;."
}

$args = @(
    $entry,
    "--name", $exeName,
    "--clean", "--noconfirm",
    "--log-level", "WARN"
)

if ($OneFile) { $args += "--onefile" } else { $args += "--onedir" }
if ($NoWindow) { $args += "--windowed" } else { $args += "--console" }
if ($IconPath) { $args += @("--icon", $IconPath) }

foreach ($h in $hidden)  { $args += @("--hidden-import", $h) }
foreach ($d in $addData) { $args += @("--add-data", $d) }

# Exclude để gọn
$args += @("--exclude-module", "tkinter.test", "--exclude-module", "sqlite3.test")

Write-Host "  pyinstaller $($args -join ' ')" -ForegroundColor DarkGray

& $venvPython -m PyInstaller @args
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed ($LASTEXITCODE)" }

# ── 4. Kết quả ──────────────────────────────────────────────────────

$distExe = if ($OneFile) { Join-Path $Root "dist\$exeName.exe" } else { Join-Path $Root "dist\$exeName\$exeName.exe" }
if (Test-Path $distExe) {
    $sizeMB = [math]::Round((Get-Item $distExe).Length / 1MB, 1)
    Write-Ok "Build OK: $distExe ($sizeMB MB)"
    Write-Host ""
    Write-Host "  Chạy thử:  `"$distExe`" --help" -ForegroundColor Yellow
    Write-Host "  Chạy nền:  `"$distExe`" --minimized" -ForegroundColor Yellow
    Write-Host "  Mở UI:     http://${HostAddr}:$Port/app/" -ForegroundColor White
    Write-Host ""
    Write-Host "  Tạo shortcut autostart:" -ForegroundColor DarkGray
    Write-Host "    powershell -ExecutionPolicy Bypass -File setup-autostart.ps1 -ExePath `"$distExe`"" -ForegroundColor DarkGray
} else {
    throw "Không tìm thấy $distExe sau build"
}

# Gợi ý tạo installer ZIP
$zipOut = Join-Path $Root "dist\novel2epub-tray.zip"
if ($OneFile -and (Test-Path $distExe)) {
    try {
        Compress-Archive -Path $distExe -DestinationPath $zipOut -Force
        Write-Ok "ZIP: $zipOut"
    } catch { Write-Warn "Không tạo được ZIP: $_" }
}
