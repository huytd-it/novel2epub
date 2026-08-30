# setup-autostart.ps1 - Đăng ký novel2epub chạy nền khi đăng nhập
# Hỗ trợ cả 2 chế độ:
#   - Tray exe (khuyên dùng): dist/novel2epub-tray.exe --minimized  (HKCU Run, không cần admin)
#   - Legacy uvicorn: Task Scheduler (cần admin)
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File setup-autostart.ps1
#   powershell -ExecutionPolicy Bypass -File setup-autostart.ps1 -ExePath "D:\Projects\novel2epub\dist\novel2epub-tray.exe"
#   powershell -ExecutionPolicy Bypass -File setup-autostart.ps1 -Remove          # gỡ
#   powershell -ExecutionPolicy Bypass -File setup-autostart.ps1 -UseTaskScheduler # ép dùng Task Scheduler

param(
    [string]$TaskName = "Novel2epubWebUI",
    [string]$ExePath = "",
    [string]$Python = "",
    [string]$WorkingDir = "",
    [switch]$Remove,
    [switch]$UseTaskScheduler
)

$ErrorActionPreference = "Stop"

# Tự đoán WorkingDir nếu không truyền
if (-not $WorkingDir) { $WorkingDir = (Resolve-Path "$PSScriptRoot").Path }

# Tìm exe tray mặc định
if (-not $ExePath) {
    $cands = @(
        (Join-Path $WorkingDir "dist\novel2epub-tray.exe"),
        (Join-Path $WorkingDir "dist\novel2epub-tray\novel2epub-tray.exe")
    )
    foreach ($c in $cands) { if (Test-Path $c) { $ExePath = $c; break } }
}

# ── Gỡ ──────────────────────────────────────────────────────────────
if ($Remove) {
    Write-Host "Gỡ autostart..." -ForegroundColor Cyan
    # 1. HKCU Run
    try {
        $reg = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
        if (Get-ItemProperty -Path $reg -Name "novel2epub" -ErrorAction SilentlyContinue) {
            Remove-ItemProperty -Path $reg -Name "novel2epub" -Force
            Write-Host "  Đã xóa HKCU Run\novel2epub" -ForegroundColor Green
        }
    } catch { Write-Host "  HKCU: $_" -ForegroundColor Yellow }

    # 2. Task Scheduler
    try {
        $t = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($t) {
            Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
            Write-Host "  Đã xóa Task '$TaskName'" -ForegroundColor Green
        }
    } catch { Write-Host "  Task: $_" -ForegroundColor Yellow }

    # 3. Startup shortcut
    $startup = [Environment]::GetFolderPath("Startup")
    $lnk = Join-Path $startup "novel2epub.lnk"
    if (Test-Path $lnk) { Remove-Item $lnk -Force; Write-Host "  Đã xóa $lnk" -ForegroundColor Green }

    Write-Host "Xong." -ForegroundColor Green
    return
}

# ── Đăng ký ─────────────────────────────────────────────────────────

# Ưu tiên tray exe (không cần admin)
if ($ExePath -and (Test-Path $ExePath) -and -not $UseTaskScheduler) {
    $ExePath = (Resolve-Path $ExePath).Path
    Write-Host "Đăng ký autostart (HKCU Run) -> $ExePath --minimized" -ForegroundColor Cyan
    $reg = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
    $cmd = "`"$ExePath`" --minimized"
    try {
        # Đảm bảo key tồn tại
        if (-not (Test-Path $reg)) { New-Item -Path $reg -Force | Out-Null }
        Set-ItemProperty -Path $reg -Name "novel2epub" -Value $cmd -Type String -Force
        Write-Host "  OK: HKCU\...\Run\novel2epub = $cmd" -ForegroundColor Green
        Write-Host "  (Không cần admin, chạy khi user đăng nhập)" -ForegroundColor DarkGray

        # Cũng tạo shortcut trong Startup làm backup (một số AV chặn Run)
        try {
            $startup = [Environment]::GetFolderPath("Startup")
            $lnk = Join-Path $startup "novel2epub.lnk"
            $ws = New-Object -ComObject WScript.Shell
            $sc = $ws.CreateShortcut($lnk)
            $sc.TargetPath = $ExePath
            $sc.Arguments = "--minimized"
            $sc.WorkingDirectory = Split-Path $ExePath
            $sc.Description = "novel2epub tray — chạy nền"
            $sc.Save()
            Write-Host "  + Shortcut: $lnk" -ForegroundColor DarkGray
        } catch { Write-Host "  (Bỏ qua shortcut: $_)" -ForegroundColor Yellow }

        Write-Host "`nGỡ: powershell -ExecutionPolicy Bypass -File setup-autostart.ps1 -Remove" -ForegroundColor Yellow
        return
    } catch {
        Write-Host "  HKCU failed: $_" -ForegroundColor Yellow
        Write-Host "  Thử Task Scheduler..." -ForegroundColor Yellow
    }
}

# Fallback: Task Scheduler (cần admin)
Write-Host "Đăng ký Task Scheduler '$TaskName'..." -ForegroundColor Cyan

# Xác định lệnh chạy
if ($ExePath -and (Test-Path $ExePath)) {
    $exe = (Resolve-Path $ExePath).Path
    $action = New-ScheduledTaskAction -Execute $exe -Argument "--minimized" -WorkingDirectory (Split-Path $exe)
} else {
    if (-not $Python) {
        $venvPy = Join-Path $WorkingDir ".venv\Scripts\pythonw.exe"
        if (Test-Path $venvPy) { $Python = $venvPy }
        else {
            $venvPy = Join-Path $WorkingDir ".venv\Scripts\python.exe"
            if (Test-Path $venvPy) { $Python = $venvPy }
            else { $Python = "python" }
        }
    }
    $Python = (Resolve-Path $Python -ErrorAction SilentlyContinue).Path
    if (-not $Python) { $Python = "python" }
    $action = New-ScheduledTaskAction -Execute $Python -Argument "desktop/tray_app.py --minimized" -WorkingDirectory $WorkingDir
    if ($ExePath) { Write-Host "  Exe chưa build, dùng: $Python desktop/tray_app.py --minimized" -ForegroundColor Yellow }
}

$trigger  = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Highest
$task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description "novel2epub tray — chạy nền khi đăng nhập"

try {
    Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null
    Write-Host "  OK: Task '$TaskName'" -ForegroundColor Green
    Write-Host "  Test: schtasks /run /tn $TaskName" -ForegroundColor Yellow
    Write-Host "  Gỡ:   powershell -ExecutionPolicy Bypass -File setup-autostart.ps1 -Remove" -ForegroundColor Yellow
} catch {
    Write-Host "  Cần chạy PowerShell với quyền Admin để tạo Task." -ForegroundColor Red
    Write-Host "  Hoặc build exe trước rồi chạy lại script này (sẽ dùng HKCU, không cần admin)." -ForegroundColor Yellow
    throw
}
