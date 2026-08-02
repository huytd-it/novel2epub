#Requires -RunAsAdministrator

param(
    [string]$TaskName = "Novel2epubWebUI",
    [string]$Python = "C:\Users\huytd\AppData\Local\Programs\Python\Python311\python.exe",
    [string]$WorkingDir = "D:\Projects\novel2epub"
)

$action = New-ScheduledTaskAction `
    -Execute $Python `
    -Argument "-m uvicorn app.main:app --host 127.0.0.1 --port 8000" `
    -WorkingDirectory $WorkingDir
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

$task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Description "Auto-start Novel2epub Web UI on logon"
Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force

Write-Host "Created task '$TaskName' to run the Web UI on port 8000 at logon" -ForegroundColor Green
Write-Host "Run 'schtasks /run /tn $TaskName' to test now" -ForegroundColor Yellow
