# run.ps1 - Chay production SPA (uvicorn, khong con Jinja2)
# Tu dong lay port tu .env hoac random, tu check env va DB
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/run.ps1
#   powershell -ExecutionPolicy Bypass -File scripts/run.ps1 -Port 8010 -HostAddr 127.0.0.1 -NoBuild -Reload

param(
    [Nullable[int]]$Port = $null,
    [string]$HostAddr = "",
    [switch]$NoBuild,
    [switch]$Reload,
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
    $py = (Join-Path $Root ".venv\Scripts\python.exe"); if(-not (Test-Path $py)){ $py="python" }
    $code="import socket,random,sys;host=sys.argv[1];pref=int(sys.argv[2]);`n"
    $code+="def is_free(p):`n import socket as s;`n sock=s.socket(s.AF_INET,s.SOCK_STREAM);sock.settimeout(0.5);`n try:sock.bind((host,p));sock.close();return True`n except:return False`n"
    $code+="if pref and pref!=0 and is_free(pref):print(pref);sys.exit(0)`n"
    $code+="for _ in range(30):`n p=random.randint(8000,9500)`n if is_free(p):print(p);sys.exit(0)`n"
    $code+="import socket as sk;s=sk.socket(sk.AF_INET,sk.SOCK_STREAM);s.bind((host,0));print(s.getsockname()[1])"
    try{ $out=& $py -c $code $hostToCheck "$pref" 2>$null; $p=[int]$out.Trim(); if($p -gt 0){return $p} }catch{}
    for($i=0;$i -lt 30;$i++){ $p=Get-Random -Minimum 8000 -Maximum 9500; try{$l=New-Object Net.Sockets.TcpListener([Net.IPAddress]::Parse($hostToCheck),$p);$l.Start();$l.Stop();return $p}catch{}}
    return 8010
}

$envInfo = Get-EnvPort -EnvPath $EnvFile
$resolvedHost = if($HostAddr){$HostAddr} elseif($envInfo.Host){$envInfo.Host} else {"127.0.0.1"}
if($Port -ne $null -and $Port -ne 0){ $resolvedPort=[int]$Port } elseif($envInfo.Port -ne $null -and $envInfo.Port -ne 0){ $resolvedPort=Find-FreePort $resolvedHost $envInfo.Port; if($resolvedPort -ne $envInfo.Port){Write-Warn "Port $($envInfo.Port) ban -> $resolvedPort"} } else { $resolvedPort=Find-FreePort $resolvedHost 0; if(-not (Test-Path (Join-Path $Root ".env"))){ "N2E_TRAY_PORT=$resolvedPort`nN2E_TRAY_HOST=$resolvedHost`n" | Set-Content (Join-Path $Root ".env") -Encoding utf8; Write-Ok "Da tao .env PORT=$resolvedPort" } }
$env:N2E_TRAY_PORT="$resolvedPort"; $env:N2E_TRAY_HOST="$resolvedHost"
$Port=$resolvedPort; $HostAddr=$resolvedHost

$venvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Warn ".venv chua co - tao moi + pip install"
    python -m venv .venv
    $venvPython = Join-Path $Root ".venv\Scripts\python.exe"
    $oldEA=$ErrorActionPreference; $ErrorActionPreference="Continue"
    & $venvPython -m pip install -r requirements.txt --quiet 2>&1 | Out-Null
    $ErrorActionPreference=$oldEA
}

$dbFile = if ($DbPath) { $DbPath } elseif ($env:NOVEL2EPUB_DB) { $env:NOVEL2EPUB_DB } else { Join-Path $Root "novel2epub.db" }
if (-not (Test-Path $dbFile)) {
    Write-Step "DB chua co - init $dbFile"
    & $venvPython scripts/init_db.py --db $dbFile
} else { Write-Ok "DB: $dbFile" }

$built = Test-Path (Join-Path $Root "app\webui\index.html")
if (-not $built -and -not $NoBuild) {
    Write-Warn "Chua co app/webui/index.html - build frontend truoc..."
    Push-Location (Join-Path $Root "frontend")
    if (-not (Test-Path "node_modules")) { npm install }
    $oldEA=$ErrorActionPreference; $ErrorActionPreference="Continue"
    npm run build 2>&1 | Write-Host
    $ErrorActionPreference=$oldEA
    Pop-Location
} elseif (-not $built) {
    Write-Warn "Chua build frontend - SPA /app se 404"
} else { Write-Ok "SPA bundle: app/webui/index.html OK" }

Write-Step "Khoi dong production SPA - http://${HostAddr}:$Port"
Write-Host "  SPA  : http://${HostAddr}:$Port/app/" -ForegroundColor White
Write-Host "  Docs : http://${HostAddr}:$Port/docs" -ForegroundColor DarkGray
Write-Host "  .env : $EnvFile -> $Port" -ForegroundColor DarkGray

$uvArgs = @("-m", "uvicorn", "app.main:app", "--host", $HostAddr, "--port", "$Port")
if ($Reload) { $uvArgs += "--reload" }
& $venvPython @uvArgs
