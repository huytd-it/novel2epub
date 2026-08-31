#Requires -Version 5.1
<#
.SYNOPSIS
    Dev mode: backend + Vite SPA.
#>
param(
    [Nullable[int]]$Port = $null,
    [switch]$SkipInstall,
    [string]$DbPath = "",
    [string]$EnvFile = ".env"
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Write-Step($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Write-Ok($m)   { Write-Host "  [OK] $m" -ForegroundColor Green }
function Write-Warn($m) { Write-Host "  [!] $m" -ForegroundColor Yellow }

function Get-EnvPort {
    param([string]$EnvPath)
    $p = $null; $h = $null
    foreach ($k in @("N2E_TRAY_PORT", "PORT", "N2E_PORT")) {
        $raw = $null
        $v = [Environment]::GetEnvironmentVariable($k)
        if ($v) { $raw = $v }
        else {
            $it = Get-Item -Path "env:$k" -ErrorAction SilentlyContinue
            if ($it -and $it.Value) { $raw = $it.Value }
        }
        if ($raw) { try { $p = [int]$raw.Trim(); break } catch {} }
    }
    foreach ($k in @("N2E_TRAY_HOST", "HOST")) {
        $raw = $null
        $v = [Environment]::GetEnvironmentVariable($k)
        if ($v) { $raw = $v }
        else {
            $it = Get-Item -Path "env:$k" -ErrorAction SilentlyContinue
            if ($it -and $it.Value) { $raw = $it.Value }
        }
        if ($raw) { $h = $raw.Trim(); break }
    }
    if ($null -ne $p) { return @{ Port = $p; Host = $h; File = "env var" } }
    $cands = @()
    if ($EnvPath) { $cands += $EnvPath }
    $cands += @("$Root\.env", ".env")
    foreach ($c in $cands | Select-Object -Unique) {
        $f = if ([IO.Path]::IsPathRooted($c)) { $c } else { Join-Path $Root $c }
        if (Test-Path $f) {
            foreach ($line in Get-Content $f -Encoding utf8) {
                $t = $line.Trim()
                if (-not $t -or $t.StartsWith("#")) { continue }
                if ($t.StartsWith("export ")) { $t = $t.Substring(7).Trim() }
                if ($t -notmatch "=") { continue }
                $kv = $t.Split("=", 2); $k = $kv[0].Trim(); $v = $kv[1].Trim().Trim('"').Trim("'")
                if ($k -in @("N2E_TRAY_PORT", "PORT", "N2E_PORT") -and $null -eq $p) { try { $p = [int]$v } catch {} }
                if ($k -in @("N2E_TRAY_HOST", "HOST") -and $null -eq $h) { $h = $v }
            }
            if ($null -ne $p) { return @{ Port = $p; Host = $h; File = $f } }
        }
    }
    return @{ Port = $p; Host = $h; File = $null }
}

function Find-FreePort($hostToCheck, $pref) {
    $py = (Join-Path $Root ".venv\Scripts\python.exe")
    if (-not (Test-Path $py)) { $py = "python" }
    $code = "import socket,random,sys;host=sys.argv[1];pref=int(sys.argv[2]);`n"
    $code += "def is_free(p):`n import socket as s;`n sock=s.socket(s.AF_INET,s.SOCK_STREAM);sock.settimeout(0.5);`n try:sock.bind((host,p));sock.close();return True`n except:return False`n"
    $code += "if pref and pref!=0 and is_free(pref):print(pref);sys.exit(0)`n"
    $code += "for _ in range(30):`n p=random.randint(8000,9500)`n if is_free(p):print(p);sys.exit(0)`n"
    $code += "import socket as sk;s=sk.socket(sk.AF_INET,sk.SOCK_STREAM);s.bind((host,0));print(s.getsockname()[1])"
    try { $out = & $py -c $code $hostToCheck "$pref" 2>$null; $p = [int]$out.Trim(); if ($p -gt 0) { return $p } } catch {}
    for ($i = 0; $i -lt 30; $i++) { $p = Get-Random -Minimum 8000 -Maximum 9500; try { $l = New-Object Net.Sockets.TcpListener([Net.IPAddress]::Parse($hostToCheck), $p); $l.Start(); $l.Stop(); return $p } catch {} }
    return 8011
}

# -- Resolve port --
$envInfo = Get-EnvPort -EnvPath $EnvFile
if ($null -ne $Port -and $Port -ne 0) { $resolvedPort = [int]$Port }
elseif ($null -ne $envInfo.Port -and $envInfo.Port -ne 0) { $resolvedPort = Find-FreePort "127.0.0.1" $envInfo.Port; if ($resolvedPort -ne $envInfo.Port) { Write-Warn "Port $($envInfo.Port) ban -> $resolvedPort" } }
else { $resolvedPort = Find-FreePort "127.0.0.1" 0 }
Write-Host "  Port: $resolvedPort (env: $($envInfo.File))" -ForegroundColor White

# 1. Python venv
Write-Step "Kiem tra Python & venv"
$venvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Warn ".venv chua co - tao moi..."
    python -m venv .venv
    $venvPython = Join-Path $Root ".venv\Scripts\python.exe"
}
Write-Ok "Python: $(& $venvPython --version 2>&1)"

# 2. Deps
if (-not $SkipInstall) {
    Write-Step "Cai dat dependencies Python"
    $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    & $venvPython -m pip install --upgrade pip --quiet 2>&1 | Out-Null
    $ErrorActionPreference = $old
    $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    & $venvPython -m pip install -r requirements.txt --quiet 2>&1 | Out-Null
    $ErrorActionPreference = $old
    $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    try { & $venvPython -m scrapling install 2>&1 | Out-Null; Write-Ok "scrapling OK" } catch { Write-Warn "scrapling skip" }
    $ErrorActionPreference = $old
} else {
    Write-Warn "SkipInstall"
}

# 3. DB
$dbFile = if ($DbPath) { $DbPath } elseif ($env:NOVEL2EPUB_DB) { $env:NOVEL2EPUB_DB } else { Join-Path $Root "novel2epub.db" }
if (-not (Test-Path $dbFile)) {
    Write-Step "DB chua co - init $dbFile"
    $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    & $venvPython scripts/init_db.py --db $dbFile 2>&1 | Write-Host
    $ErrorActionPreference = $old
} else { Write-Ok "DB: $dbFile" }

# 4. Frontend
Write-Step "Kiem tra frontend deps"
if (-not (Test-Path (Join-Path $Root "frontend\node_modules"))) {
    if (-not $SkipInstall) {
        Push-Location (Join-Path $Root "frontend")
        try {
            $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
            npm install 2>&1 | Write-Host
            $ErrorActionPreference = $old
        } finally { Pop-Location }
    } else { Write-Warn "node_modules thieu nhung SkipInstall" }
} else { Write-Ok "frontend/node_modules OK" }

# 5. Start
Write-Step "Khoi dong DEV - backend :$resolvedPort + Vite :5183 (SPA only)"
Write-Host "  Backend : http://127.0.0.1:$resolvedPort" -ForegroundColor White
Write-Host "  SPA dev : http://localhost:5183/ (proxy /api -> 127.0.0.1:$resolvedPort)" -ForegroundColor White
Write-Host "  Bam Ctrl+C de dung" -ForegroundColor Yellow

$backendJob = Start-Process -FilePath $venvPython -ArgumentList @("-m", "uvicorn", "app.main:app", "--reload", "--port", "$resolvedPort", "--host", "127.0.0.1") -WorkingDirectory $Root -PassThru
Write-Ok "Backend PID $($backendJob.Id) - doi 2s..."
Start-Sleep -Seconds 2
if ($backendJob.HasExited) {
    Write-Host "  [ERR] Backend thoat som (exit $($backendJob.ExitCode))" -ForegroundColor Red
    exit 1
}
try {
    Push-Location (Join-Path $Root "frontend")
    try {
        if ($resolvedPort -ne 8011) { $env:N2E_DEV_API_TARGET = "http://127.0.0.1:$resolvedPort" }
        $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
        npm run dev 2>&1 | Write-Host
        $ErrorActionPreference = $old
    } finally { Pop-Location }
} finally {
    if (-not $backendJob.HasExited) {
        Write-Host "`nDung backend PID $($backendJob.Id)..." -ForegroundColor Yellow
        Stop-Process -Id $backendJob.Id -Force -ErrorAction SilentlyContinue
    }
}
