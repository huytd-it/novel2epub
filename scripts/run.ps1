#Requires -Version 5.1
<#
.SYNOPSIS
    Chay production SPA (uvicorn, 1 port cho ca API + WebUI).
#>
param(
    [Nullable[int]]$Port = $null,
    [string]$HostAddr = "",
    [switch]$NoBuild,
    [switch]$Reload,
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
    return 8010
}

$envInfo = Get-EnvPort -EnvPath $EnvFile
$resolvedHost = if ($HostAddr) { $HostAddr } elseif ($envInfo.Host) { $envInfo.Host } else { "127.0.0.1" }
if ($null -ne $Port -and $Port -ne 0) { $resolvedPort = [int]$Port }
elseif ($null -ne $envInfo.Port -and $envInfo.Port -ne 0) { $resolvedPort = Find-FreePort $resolvedHost $envInfo.Port; if ($resolvedPort -ne $envInfo.Port) { Write-Warn "Port $($envInfo.Port) ban -> $resolvedPort" } }
else { $resolvedPort = Find-FreePort $resolvedHost 0; if (-not (Test-Path (Join-Path $Root ".env"))) { "N2E_TRAY_PORT=$resolvedPort`nN2E_TRAY_HOST=$resolvedHost`n" | Set-Content (Join-Path $Root ".env") -Encoding utf8; Write-Ok "Da tao .env PORT=$resolvedPort" } }
$env:N2E_TRAY_PORT = "$resolvedPort"; $env:N2E_TRAY_HOST = "$resolvedHost"
$Port = $resolvedPort; $HostAddr = $resolvedHost

# -- venv / DB --
$venvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Warn ".venv chua co - tao moi + pip install"
    $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    python -m venv .venv 2>&1 | Out-Null
    $ErrorActionPreference = $old
    $venvPython = Join-Path $Root ".venv\Scripts\python.exe"
    $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    & $venvPython -m pip install -r requirements.txt --quiet 2>&1 | Out-Null
    $ErrorActionPreference = $old
}

$dbFile = if ($DbPath) { $DbPath } elseif ($env:NOVEL2EPUB_DB) { $env:NOVEL2EPUB_DB } else { Join-Path $Root "novel2epub.db" }
if (-not (Test-Path $dbFile)) {
    Write-Step "DB chua co - init $dbFile"
    $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    & $venvPython scripts/init_db.py --db $dbFile 2>&1 | Write-Host
    $ErrorActionPreference = $old
} else { Write-Ok "DB: $dbFile" }

# -- SPA bundle --
$built = Test-Path (Join-Path $Root "app\webui\index.html")
if (-not $built -and -not $NoBuild) {
    Write-Warn "Chua co app/webui/index.html - build frontend truoc..."
    Push-Location (Join-Path $Root "frontend")
    try {
        if (-not (Test-Path "node_modules")) {
            $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
            npm install 2>&1 | Write-Host
            $ErrorActionPreference = $old
        }
        $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
        npm run build 2>&1 | Write-Host
        $ok = ($LASTEXITCODE -eq 0); $ErrorActionPreference = $old
        if (-not $ok) { throw "vite build failed ($LASTEXITCODE)" }
    } finally { Pop-Location }
    $built = Test-Path (Join-Path $Root "app\webui\index.html")
}
if (-not $built -and $NoBuild) { Write-Warn "Chua build frontend - SPA / se 404" }
elseif ($built) { Write-Ok "SPA bundle: app/webui/index.html OK" }

# -- start --
Write-Step "Khoi dong production SPA - http://${HostAddr}:$Port"
Write-Host "  SPA  : http://${HostAddr}:$Port/" -ForegroundColor White
Write-Host "  Docs : http://${HostAddr}:$Port/docs" -ForegroundColor DarkGray
Write-Host "  .env : $EnvFile -> $Port" -ForegroundColor DarkGray

$uvArgs = @("-m", "uvicorn", "app.main:app", "--host", $HostAddr, "--port", "$Port")
if ($Reload) { $uvArgs += "--reload" }
$old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
& $venvPython @uvArgs 2>&1 | Write-Host
$ErrorActionPreference = $old
