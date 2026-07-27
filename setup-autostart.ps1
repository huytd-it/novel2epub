<![CDATA[#Requires -RunAsAdministrator

param(
    [string]$TaskName = "Novel2epubWebUI",
    [string]$Command = "uvicorn app.main:app --port 8010",
    [string]$WorkingDir = "D:\Projects\novel2epub"
)

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -WindowStyle Hidden -Command `"cd '$WorkingDir'; $Command`""
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

$task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Description "Auto-start Novel2epub Web UI on logon"
Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force

Write-Host "Created task '$TaskName' to run at logon: $Command" -ForegroundColor Green
Write-Host "Run 'schtasks /run /tn $TaskName' to test now" -ForegroundColor Yellow
]]>