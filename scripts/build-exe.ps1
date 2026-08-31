# build-exe.ps1 - Đóng gói novel2epub thành .exe chạy ngầm (tray, không console)
# - Tự kiểm tra môi trường (Python >=3.10, Node >=18, pip, venv) và cài đặt đầy đủ
# - Tự động lấy port từ .env / biến môi trường, nếu không có hoặc bận thì chọn ngẫu nhiên port rảnh
# - Build SPA (frontend -> app/webui) rồi đóng gói PyInstaller --windowed
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/build-exe.ps1
#   powershell -ExecutionPolicy Bypass -File scripts/build-exe.ps1 -Port 8010
#   powershell -ExecutionPolicy Bypass -File scripts/build-exe.ps1 -RandomPort
#   powershell -ExecutionPolicy Bypass -File scripts/build-exe.ps1 -OneFile:$false   # onedir (khởi động nhanh)
#   powershell -ExecutionPolicy Bypass -File scripts/build-exe.ps1 -NoWindow:$false  # giữ console để debug
#   powershell -ExecutionPolicy Bypass -File scripts/build-exe.ps1 -SkipBuild -SkipInstall
#   powershell -ExecutionPolicy Bypass -File scripts/build-exe.ps1 -EnvFile ".env"
#
# Kết quả: dist/novel2epub-tray.exe (one-file, --windowed mặc định = chạy ngầm không console)
#          dist/novel2epub-tray.zip

param(
    [Nullable[int]]$Port = $null,          # null = tự lấy từ .env / random
    [string]$HostAddr = "",                # rỗng = tự lấy từ .env hoặc 127.0.0.1
    [switch]$RandomPort,                   # ép chọn port ngẫu nhiên
    [string]$EnvFile = ".env",             # file môi trường để đọc PORT/N2E_TRAY_PORT
    [switch]$OneFile = $true,
    [switch]$NoWindow = $true,             # --windowed: chạy ngầm không console
    [switch]$SkipBuild,
    [switch]$SkipInstall,
    [switch]$InstallBrowsers,              # cài browser cho scrapling (scrapling install)
    [string]$IconPath = ""
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $Root

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  ! $msg" -ForegroundColor Yellow }
function Write-Err($msg)  { Write-Host "  [ERR] $msg" -ForegroundColor Red }

# ── helper: đọc .env ─────────────────────────────────────────────
function Get-EnvPort {
    param([string]$EnvPath, [string]$HostFallback = "127.0.0.1")
    $envPort = $null
    $envHost = $null
    $envFileUsed = $null

    # 1. Biến môi trường thật (ưu tiên cao nhất trước .env)
    foreach ($k in @("N2E_TRAY_PORT", "PORT", "N2E_PORT")) {
        $v = [Environment]::GetEnvironmentVariable($k)
        if (-not $v) { $v = (Get-Item -Path "env:$k" -ErrorAction SilentlyContinue).Value }
        if ($v -and $v.Trim() -ne "") {
            try { $envPort = [int]$v.Trim(); break } catch {}
        }
    }
    foreach ($k in @("N2E_TRAY_HOST", "HOST")) {
        $v = [Environment]::GetEnvironmentVariable($k)
        if (-not $v) { $v = (Get-Item -Path "env:$k" -ErrorAction SilentlyContinue).Value }
        if ($v -and $v.Trim() -ne "") { $envHost = $v.Trim(); break }
    }
    if ($envPort -ne $null) { return @{ Port = $envPort; Host = $envHost; File = "env var" } }

    # 2. File .env
    $candidates = @()
    if ($EnvPath) { $candidates += $EnvPath }
    $candidates += @("$Root\.env", "$Root\frontend\.env", ".env")
    $candidates = $candidates | Select-Object -Unique
    foreach ($cand in $candidates) {
        $full = if ([IO.Path]::IsPathRooted($cand)) { $cand } else { Join-Path $Root $cand }
        if (Test-Path $full) {
            $envFileUsed = $full
            try {
                $lines = Get-Content $full -Encoding utf8
                foreach ($line in $lines) {
                    $t = $line.Trim()
                    if (-not $t -or $t.StartsWith("#")) { continue }
                    if ($t.StartsWith("export ")) { $t = $t.Substring(7).Trim() }
                    if ($t -notmatch "=") { continue }
                    $kv = $t.Split("=", 2)
                    $k = $kv[0].Trim()
                    $v = $kv[1].Trim().Trim('"').Trim("'")
                    if ($v.Contains(" #")) { $v = $v.Split(" #", 2)[0].Trim() }
                    if ($k -in @("N2E_TRAY_PORT", "PORT", "N2E_PORT") -and $envPort -eq $null) {
                        try { $envPort = [int]$v } catch {}
                    }
                    if ($k -in @("N2E_TRAY_HOST", "HOST") -and $envHost -eq $null) {
                        $envHost = $v
                    }
                }
            } catch {}
            if ($envPort -ne $null) { break }
        }
    }
    return @{ Port = $envPort; Host = $envHost; File = $envFileUsed }
}

function Get-Python {
    $cands = @(
        (Join-Path $Root ".venv\Scripts\python.exe"),
        (Join-Path $Root ".venv\Scripts\pythonw.exe"),
        "python", "python3", "py"
    )
    foreach ($c in $cands) {
        try {
            $cmd = Get-Command $c -ErrorAction SilentlyContinue
            if ($cmd) { return $cmd.Source }
            if (Test-Path $c) { return (Resolve-Path $c).Path }
        } catch {}
    }
    return $null
}

function Find-FreePort {
    param([string]$HostToCheck = "127.0.0.1", [int]$Preferred = 0)
    # Dùng Python để tìm port rảnh (chính xác, cross-platform)
    $py = Get-Python
    if ($py) {
        $code = @"
import socket, random
host='$HostToCheck'
preferred=$Preferred
def is_free(p):
    import socket as s
    sock=s.socket(s.AF_INET, s.SOCK_STREAM)
    sock.settimeout(0.5)
    try:
        sock.bind((host,p)); sock.close(); return True
    except: return False

if preferred and preferred != 0 and is_free(preferred):
    print(preferred)
else:
    # thử random
    for _ in range(30):
        p=random.randint(8000,9500)
        if is_free(p):
            print(p); raise SystemExit(0)
    # fallback: OS random
    sock=socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((host,0))
    print(sock.getsockname()[1])
"@
        try {
            $out = & $py -c $code 2>$null
            $p = [int]$out.Trim()
            if ($p -gt 0) { return $p }
        } catch {}
    }
    # Fallback PowerShell
    if ($Preferred -and $Preferred -ne 0) {
        try {
            $l = New-Object Net.Sockets.TcpListener([Net.IPAddress]::Parse($HostToCheck), $Preferred)
            $l.Start(); $l.Stop(); return $Preferred
        } catch {}
    }
    for ($i = 0; $i -lt 30; $i++) {
        $p = Get-Random -Minimum 8000 -Maximum 9500
        try {
            $l = New-Object Net.Sockets.TcpListener([Net.IPAddress]::Parse($HostToCheck), $p)
            $l.Start(); $l.Stop(); return $p
        } catch {}
    }
    return 8010
}

# ── 0. Kiểm tra môi trường ───────────────────────────────────────

Write-Step "Kiểm tra môi trường"

# Python
$pyCmd = $null
foreach ($c in @("python", "python3", "py")) {
    $found = Get-Command $c -ErrorAction SilentlyContinue
    if ($found) { $pyCmd = $c; break }
}
if (-not $pyCmd) { throw "Không tìm thấy Python. Cài Python 3.10+ từ https://python.org" }

$pyVer = & $pyCmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" 2>$null
$pyVerParts = $pyVer.Trim().Split(".")
$pyMajor = [int]$pyVerParts[0]; $pyMinor = [int]$pyVerParts[1]
if ($pyMajor -lt 3 -or ($pyMajor -eq 3 -and $pyMinor -lt 10)) {
    throw "Yêu cầu Python >=3.10, hiện tại $pyVer. Cập nhật Python trước."
}
Write-Ok "Python $pyVer ($pyCmd)"

# Node
$nodeOk = $false
try {
    $nodeVer = node --version 2>$null
    $npmVer = npm --version 2>$null
    if ($nodeVer) {
        $nodeNum = $nodeVer.Trim().TrimStart("v").Split(".")[0]
        if ([int]$nodeNum -lt 18) {
            Write-Warn "Node $nodeVer < 18 - khuyến nghị Node 18+ (vẫn thử build)"
        } else {
            Write-Ok "Node $nodeVer / npm $npmVer"
        }
        $nodeOk = $true
    }
} catch {}
if (-not $nodeOk) {
    Write-Warn "Không tìm thấy Node.js - build SPA sẽ bỏ qua (cài từ https://nodejs.org để có SPA /)"
}

# pip
try { & $pyCmd -m pip --version 2>$null | Out-Null; Write-Ok "pip OK" }
catch { throw "pip không khả dụng - chạy: $pyCmd -m ensurepip --upgrade" }

# ── 0b. Resolve PORT / HOST ──────────────────────────────────────

$envInfo = Get-EnvPort -EnvPath $EnvFile
$resolvedHost = if ($HostAddr) { $HostAddr } elseif ($envInfo.Host) { $envInfo.Host } else { "127.0.0.1" }

if ($Port -ne $null -and $Port -ne 0) {
    $resolvedPort = [int]$Port
    $portSource = "tham số -Port"
} elseif ($RandomPort) {
    $resolvedPort = Find-FreePort -HostToCheck $resolvedHost -Preferred 0
    $portSource = "random (-RandomPort)"
} elseif ($envInfo.Port -ne $null -and $envInfo.Port -ne 0) {
    # kiểm tra port từ env có rảnh không
    $testFree = Find-FreePort -HostToCheck $resolvedHost -Preferred $envInfo.Port
    if ($testFree -eq $envInfo.Port) {
        $resolvedPort = $envInfo.Port
        $portSource = "env/.env ($($envInfo.File))"
    } else {
        $resolvedPort = $testFree
        $portSource = "env/.env bận $($envInfo.Port) -> random $testFree"
    }
} else {
    # không có port trong env -> random
    $resolvedPort = Find-FreePort -HostToCheck $resolvedHost -Preferred 0
    $portSource = "random (không có PORT trong env/.env)"
    # Nếu .env không tồn tại, tạo mới để lần sau ổn định
    $envFilePath = Join-Path $Root ".env"
    if (-not (Test-Path $envFilePath)) {
        try {
            "N2E_TRAY_PORT=$resolvedPort`nN2E_TRAY_HOST=$resolvedHost`n" | Set-Content $envFilePath -Encoding utf8
            Write-Ok "Đã tạo .env với PORT=$resolvedPort"
            $portSource += " + ghi .env"
        } catch { Write-Warn "Không ghi được .env: $_" }
    }
}

Write-Host "  Port: $resolvedPort ($portSource)" -ForegroundColor White
Write-Host "  Host: $resolvedHost" -ForegroundColor White
# Truyền cho tray_app runtime qua env (exe cũng sẽ tự đọc .env)
$env:N2E_TRAY_PORT = "$resolvedPort"
$env:N2E_TRAY_HOST = "$resolvedHost"
# Giữ $Port / $HostAddr để log cuối
$Port = $resolvedPort
$HostAddr = $resolvedHost

# ── 1. Chuẩn bị venv & deps ──────────────────────────────────────

$venvPython = Join-Path $Root ".venv\Scripts\python.exe"
$venvPip    = Join-Path $Root ".venv\Scripts\pip.exe"

if (-not (Test-Path $venvPython)) {
    Write-Warn ".venv chưa có - tạo mới"
    & $pyCmd -m venv .venv
    if (-not (Test-Path $venvPython)) { throw "Tạo .venv thất bại" }
    Write-Ok "Đã tạo .venv"
} else {
    Write-Ok "venv: $venvPython"
}

# Upgrade pip/wheel/setuptools
if (-not $SkipInstall) {
    Write-Step "Cập nhật pip / cài deps Python"
    $oldEA = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    & $venvPython -m pip install --upgrade pip setuptools wheel -q 2>&1 | Write-Host
    $ErrorActionPreference = $oldEA
    if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed ($LASTEXITCODE)" }
    Write-Ok "pip/wheel OK"
    $oldEA = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    & $venvPython -m pip install -q -r requirements.txt 2>&1 | Write-Host
    $pipCode = $LASTEXITCODE; $ErrorActionPreference = $oldEA
    if ($pipCode -ne 0) { throw "pip install -r requirements.txt failed ($pipCode)" }
    Write-Ok "requirements.txt OK"
    $oldEA = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    & $venvPython -m pip install -q pystray pillow pyinstaller 2>&1 | Write-Host
    $pipCode = $LASTEXITCODE; $ErrorActionPreference = $oldEA
    if ($pipCode -ne 0) { throw "pip install pystray/pillow/pyinstaller failed ($pipCode)" }
    Write-Ok "pystray / pillow / pyinstaller OK"

    if ($InstallBrowsers) {
        Write-Step "Cài browser cho Scrapling (scrapling install)"
        try { & $venvPython -m scrapling install 2>&1 | Write-Host } catch { Write-Warn "scrapling install: $_" }
        try { & $venvPython -c "import scrapling; scrapling.install()" 2>&1 | Write-Host } catch {}
    }
} else {
    Write-Warn "SkipInstall - kiểm tra pyinstaller có sẵn không"
    $oldEA = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    & $venvPython -m pip show pyinstaller 2>&1 | Out-Null
    $ErrorActionPreference = $oldEA
    if ($LASTEXITCODE -ne 0) {
        Write-Step "Thiếu pyinstaller - cài bổ sung"
        & $venvPython -m pip install -q pystray pillow pyinstaller
    }
    Write-Ok "Deps OK (skip)"
}

# ── 2. Build SPA (để exe phục vụ /) ─────────────────────────────

$built = Test-Path (Join-Path $Root "app\webui\index.html")
if (-not $built -and -not $SkipBuild -and $nodeOk) {
    Write-Step "Build SPA -> app/webui (vite)"
    Push-Location (Join-Path $Root "frontend")
    try {
        if (-not (Test-Path "node_modules")) {
            Write-Host "  npm install ..." -ForegroundColor DarkGray
            $oldEA = $ErrorActionPreference; $ErrorActionPreference = "Continue"
            npm install 2>&1 | Write-Host
            $npmCode = $LASTEXITCODE; $ErrorActionPreference = $oldEA
            if ($npmCode -ne 0) { throw "npm install failed ($npmCode)" }
        }
        $oldEA = $ErrorActionPreference; $ErrorActionPreference = "Continue"
        npm run build 2>&1 | Write-Host
        $npmCode = $LASTEXITCODE; $ErrorActionPreference = $oldEA
        if ($npmCode -ne 0) { throw "vite build failed ($npmCode)" }
        Write-Ok "Vite build OK"
    } finally { Pop-Location }
    $built = Test-Path (Join-Path $Root "app\webui\index.html")
} elseif ($built) {
    Write-Ok "SPA bundle sẵn: app/webui/index.html"
} elseif (-not $nodeOk) {
    Write-Warn "Bỏ qua build SPA (thiếu Node) - / sẽ 404"
} else {
    Write-Warn "Bỏ qua build SPA (-SkipBuild) - / sẽ 404 nếu chưa có bundle"
}

# ── 3. Icon ───────────────────────────────────────────────────────

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

# ── 4. PyInstaller ────────────────────────────────────────────────

Write-Step "Đóng gói exe với PyInstaller (chạy ngầm --windowed)"

# Dọn toàn bộ config/build cũ để file ra luôn là mới nhất và đúng nhất
# (yêu cầu: build phải dọn sạch artifact cũ trước khi đóng gói)
$toClean = @(
    (Join-Path $Root "dist"),
    (Join-Path $Root "build"),
    (Join-Path $Root "novel2epub-tray.spec.bak"),
    (Join-Path $Root "novel2epub-tray.exe"),
    (Join-Path $Root "novel2epub-tray.zip")
)
foreach ($p in $toClean) {
    if (Test-Path $p) {
        try { Remove-Item -Recurse -Force $p -ErrorAction SilentlyContinue } catch {}
        Write-Host "  dọn: $p" -ForegroundColor DarkGray
    }
}
# Dist có thể còn DB/log rác từ lần chạy trước — dọn luôn nếu còn sót
foreach ($leaf in @("novel2epub.db", "novel2epub.db-shm", "novel2epub.db-wal")) {
    $dp = Join-Path $Root "dist\$leaf"
    if (Test-Path $dp) { Remove-Item -Force $dp -ErrorAction SilentlyContinue }
}
# giữ .env, không xóa

$exeName = "novel2epub-tray"
$entry   = Join-Path $Root "desktop\tray_app.py"

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
    "yaml", "PIL", "pystray",
    # Scrapling fetcher (bat len la chay duoc — chi can curl_cffi, khong doi browser)
    # Phai khai bao hidden-import vi scrapling dung lazy __getattr__ (ma PyInstaller khong tu dong duoc)
    "scrapling", "scrapling.fetchers", "scrapling.fetchers.requests",
    "scrapling.parser", "scrapling.core.custom_types", "scrapling.core.utils",
    "scrapling.core._types", "scrapling.engines.static", "scrapling.engines.toolbelt.custom",
    "scrapling.engines.toolbelt.convertor", "scrapling.engines.constants",
    "playwright", "playwright.sync_api", "playwright.async_api",
    "curl_cffi", "curl_cffi.requests",
    "charset_normalizer", "lxml", "cssselect"
)

$addData = @()
if ($built) { $addData += "app/webui;app/webui" }
if (Test-Path (Join-Path $Root "frontend\src-tauri\icons")) { $addData += "frontend/src-tauri/icons;frontend/src-tauri/icons" }
if (Test-Path (Join-Path $Root "novel2epub.example.yaml")) { $addData += "novel2epub.example.yaml;." }
if (Test-Path (Join-Path $Root "sources.yaml")) { $addData += "sources.yaml;." }
# kèm .env nếu có để exe đọc mặc định port
if (Test-Path (Join-Path $Root ".env")) { $addData += ".env;." }

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

# Thu gom toan bo scrapling + curl_cffi + playwright (dam bao _wrapper.pyd va data files duoc bundle)
# scrapling 0.4+ import playwright ngay ca trong fetcher path (toolbelt.convertor) nen
# phai bundle playwright — neu exclude thi fetcher cung loi "Chua cai scrapling" trong exe.
$args += @("--collect-all", "scrapling", "--collect-all", "curl_cffi", "--collect-all", "playwright")

$args += @("--exclude-module", "tkinter.test", "--exclude-module", "sqlite3.test")
# Loại trừ các module nặng không cần cho exe tray (giảm thời gian build + dung lượng)
# torch (+cu128 ~2GB) không cần cho chế độ API/translate online; nếu cần local MT thì user tự cài.
$heavyExcludes = @(
    "torch", "torch.utils.tensorboard", "tensorboard",
    "scipy", "trimesh", "shapely", "networkx", "rtree",
    "Crawl4AI"
)
foreach ($hm in $heavyExcludes) { $args += @("--exclude-module", $hm) }

Write-Host "  pyinstaller $($args -join ' ')" -ForegroundColor DarkGray
Write-Host "  PORT=$Port HOST=$HostAddr (truyền vào exe qua env/.env)" -ForegroundColor DarkGray

$oldEA = $ErrorActionPreference; $ErrorActionPreference = "Continue"
& $venvPython -m PyInstaller @args 2>&1 | ForEach-Object { Write-Host $_ }
$pyiCode = $LASTEXITCODE; $ErrorActionPreference = $oldEA
if ($pyiCode -ne 0) { throw "PyInstaller failed ($pyiCode)" }

# ── 5. Kết quả + copy ra ngoài cùng (root) ─────────────────────

$distExe = if ($OneFile) { Join-Path $Root "dist\$exeName.exe" } else { Join-Path $Root "dist\$exeName\$exeName.exe" }
# Copy exe ra thư mục gốc để chạy với DB ngoài (không tạo DB riêng trong dist)
$rootExe = Join-Path $Root "$exeName.exe"
if (Test-Path $distExe) {
    try {
        Copy-Item $distExe $rootExe -Force
        Write-Ok "Đã copy ra ngoài: $rootExe (dùng DB $Root\novel2epub.db, không xóa DB)"
        # Không để lại DB rác trong dist (nếu PyInstaller/tray tạo nhầm)
        Remove-Item (Join-Path $Root "dist\novel2epub.db") -Force -ErrorAction SilentlyContinue
        Remove-Item (Join-Path $Root "dist\novel2epub.db-shm") -Force -ErrorAction SilentlyContinue
        Remove-Item (Join-Path $Root "dist\novel2epub.db-wal") -Force -ErrorAction SilentlyContinue
        Remove-Item (Join-Path $Root "dist\logs") -Recurse -Force -ErrorAction SilentlyContinue
    } catch { Write-Warn "Không copy được ra root: $_" }
}
if (Test-Path $distExe) {
    $sizeMB = [math]::Round((Get-Item $distExe).Length / 1MB, 1)
    Write-Ok "Build OK: $distExe ($sizeMB MB) - chạy ngầm (no console)"
    Write-Host ""
    Write-Host "  Chạy thử (help):  `"$distExe`" --help" -ForegroundColor Yellow
    Write-Host "  Chạy nền:         `"$distExe`" --minimized" -ForegroundColor Yellow
    Write-Host "  Port tự chọn:     $Port (từ $portSource)" -ForegroundColor White
    Write-Host "  Mở UI:            http://${HostAddr}:$Port/" -ForegroundColor White
    if ($NoWindow) {
        Write-Host "  Ghi chú: exe --windowed nên double-click sẽ ẩn xuống khay (không hiện console)" -ForegroundColor DarkGray
        Write-Host "           Xem log: logs/tray.log  hoặc  logs/port.txt" -ForegroundColor DarkGray
    }
    Write-Host ""
    Write-Host "  Tạo autostart (không cần admin):" -ForegroundColor DarkGray
    Write-Host "    powershell -ExecutionPolicy Bypass -File setup-autostart.ps1 -ExePath `"$distExe`"" -ForegroundColor DarkGray
    Write-Host "  Đổi port: sửa .env (N2E_TRAY_PORT=...) rồi chạy lại exe, hoặc: `"$distExe`" --port 0  (random)" -ForegroundColor DarkGray
} else {
    throw "Không tìm thấy $distExe sau build"
}

$zipOut = Join-Path $Root "dist\novel2epub-tray.zip"
if ($OneFile -and (Test-Path $distExe)) {
    try {
        if (Test-Path $zipOut) { Remove-Item $zipOut -Force }
        Compress-Archive -Path $distExe -DestinationPath $zipOut -Force
        Write-Ok "ZIP: $zipOut"
        # Zip cũng copy ra root cho tiện
        Copy-Item $zipOut (Join-Path $Root "novel2epub-tray.zip") -Force -ErrorAction SilentlyContinue
    } catch { Write-Warn "Không tạo được ZIP: $_" }
}

Write-Host "`nHoàn tất. Exe ngoài cùng: $rootExe (dùng DB ngoài, không xóa DB)" -ForegroundColor Green
