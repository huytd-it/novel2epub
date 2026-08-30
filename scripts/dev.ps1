# dev.ps1 - Dev mode: backend + Vite SPA (khong con Jinja2)
# Tu dong kiem tra moi truong, lay port tu .env hoac random
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/dev.ps1
#   powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 -Port 8011 -SkipInstall

param(
    [Nullable[int]]$Port = $null,
    [switch]$SkipInstall,
    [string]$DbPath = "",
    [string]$EnvFile = ".env"
)

$ErrorActionPreference = "Continue"
$Root = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $Root

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  [!] $msg" -ForegroundColor Yellow }

function Get-EnvPort {
    param([string]$EnvPath)
    $p=$null; $h=$null
    foreach($k in @("N2E_TRAY_PORT","PORT","N2E_PORT")){
        $v=[Environment]::GetEnvironmentVariable($k); if(-not $v){$v=(Get-Item "env:$k" -ErrorAction SilentlyContinue).Value}
        if($v){ try{$p=[int]$v.Trim();break}catch{}}
    }
    foreach($k in @("N2E_TRAY_HOST","HOST")){
        $v=[Environment]::GetEnvironmentVariable($k); if(-not $v){$v=(Get-Item "env:$k" -ErrorAction SilentlyContinue).Value}
        if($v){$h=$v.Trim();break}
    }
    if($p -ne $null){return @{Port=$p;Host=$h;File="env var"}}
    $cands=@(); if($EnvPath){$cands+=$EnvPath}; $cands+=@("$Root\.env",".env")
    foreach($c in $cands | Select-Object -Unique){
        $f=if([IO.Path]::IsPathRooted($c)){$c}else{Join-Path $Root $c}
        if(Test-Path $f){
            foreach($line in Get-Content $f -Encoding utf8){
                $t=$line.Trim(); if(-not $t -or $t.StartsWith("#")){continue}
                if($t.StartsWith("export ")){$t=$t.Substring(7).Trim()}
                if($t -notmatch "="){continue}
                $kv=$t.Split("=",2); $k=$kv[0].Trim(); $v=$kv[1].Trim().Trim('"').Trim("'")
                if($k -in @("N2E_TRAY_PORT","PORT","N2E_PORT") -and $p -eq $null){try{$p=[int]$v}catch{}}
                if($k -in @("N2E_TRAY_HOST","HOST") -and $h -eq $null){$h=$v}
            }
            if($p -ne $null){return @{Port=$p;Host=$h;File=$f}}
        }
    }
    return @{Port=$p;Host=$h;File=$null}
}

function Find-FreePort($hostToCheck, $pref){
    $py = (Join-Path $Root ".venv\Scripts\python.exe")
    if(-not (Test-Path $py)){ $py="python" }
    $code="import socket,random,sys;host=sys.argv[1];pref=int(sys.argv[2]);`n"
    $code+="def is_free(p):`n import socket as s;`n sock=s.socket(s.AF_INET,s.SOCK_STREAM);sock.settimeout(0.5);`n try:sock.bind((host,p));sock.close();return True`n except:return False`n"
    $code+="if pref and pref!=0 and is_free(pref):print(pref);sys.exit(0)`n"
    $code+="for _ in range(30):`n p=random.randint(8000,9500)`n if is_free(p):print(p);sys.exit(0)`n"
    $code+="import socket as sk;s=sk.socket(sk.AF_INET,sk.SOCK_STREAM);s.bind((host,0));print(s.getsockname()[1])"
    try{ $out=& $py -c $code $hostToCheck "$pref" 2>$null; $p=[int]$out.Trim(); if($p -gt 0){return $p} }catch{}
    for($i=0;$i -lt 30;$i++){ $p=Get-Random -Minimum 8000 -Maximum 9500; try{$l=New-Object Net.Sockets.TcpListener([Net.IPAddress]::Parse($hostToCheck),$p);$l.Start();$l.Stop();return $p}catch{}}
    return 8011
}

# -- Resolve port
$envInfo = Get-EnvPort -EnvPath $EnvFile
$defaultPort = 8011
if($Port -ne $null -and $Port -ne 0){ $resolvedPort=[int]$Port } elseif($envInfo.Port -ne $null -and $envInfo.Port -ne 0){ $resolvedPort=Find-FreePort "127.0.0.1" $envInfo.Port; if($resolvedPort -ne $envInfo.Port){Write-Warn "Port $($envInfo.Port) ban -> $resolvedPort"} } else { $resolvedPort=Find-FreePort "127.0.0.1" 0 }
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
    $oldEA=$ErrorActionPreference; $ErrorActionPreference="Continue"
    & $venvPython -m pip install --upgrade pip --quiet 2>&1 | Out-Null
    & $venvPython -m pip install -r requirements.txt 2>&1 | Out-Null
    $ErrorActionPreference=$oldEA
    try { & $venvPython -m scrapling install 2>&1 | Out-Null; Write-Ok "scrapling OK" } catch { Write-Warn "scrapling skip" }
} else { Write-Warn "SkipInstall" }

# 3. DB
$dbFile = if ($DbPath) { $DbPath } elseif ($env:NOVEL2EPUB_DB) { $env:NOVEL2EPUB_DB } else { Join-Path $Root "novel2epub.db" }
if (-not (Test-Path $dbFile)) {
    Write-Step "DB chua co - init $dbFile"
    & $venvPython scripts/init_db.py --db $dbFile
} else { Write-Ok "DB: $dbFile" }

# 4. Frontend
Write-Step "Kiem tra frontend deps"
if (-not (Test-Path (Join-Path $Root "frontend\node_modules"))) {
    if (-not $SkipInstall) {
        Push-Location (Join-Path $Root "frontend"); npm install; Pop-Location
    } else { Write-Warn "node_modules thieu nhung SkipInstall" }
} else { Write-Ok "frontend/node_modules OK" }

# 5. Start
Write-Step "Khoi dong DEV - backend :$resolvedPort + Vite :5183 (SPA only)"
Write-Host "  Backend : http://127.0.0.1:$resolvedPort" -ForegroundColor White
Write-Host "  SPA dev : http://localhost:5183/app/ (proxy /api -> 127.0.0.1:$resolvedPort)" -ForegroundColor White
Write-Host "  Bam Ctrl+C de dung" -ForegroundColor Yellow

$backendJob = Start-Process -FilePath $venvPython -ArgumentList "-m","uvicorn","app.main:app","--reload","--port","$resolvedPort" -WorkingDirectory $Root -PassThru
Write-Ok "Backend PID $($backendJob.Id) - doi 2s..."
Start-Sleep -Seconds 2
try {
    Push-Location (Join-Path $Root "frontend")
    if ($resolvedPort -ne 8011) { $env:N2E_DEV_API_TARGET = "http://127.0.0.1:$resolvedPort" }
    npm run dev
} finally {
    Pop-Location
    if (-not $backendJob.HasExited) {
        Write-Host "`nDung backend PID $($backendJob.Id)..." -ForegroundColor Yellow
        Stop-Process -Id $backendJob.Id -Force -ErrorAction SilentlyContinue
    }
}
