$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Runner = Join-Path $PSScriptRoot 'run-daily.ps1'
$TaskName = 'WorldCupPredict-Daily-1300'
$LegacyTaskNames = @('WorldCupPredict-Daily-1800', 'WorldCupPredict-Daily-2200')
$StartAt = [datetime]'2026-06-17T13:00:00'

foreach ($LegacyTaskName in $LegacyTaskNames) {
    if (Get-ScheduledTask -TaskName $LegacyTaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $LegacyTaskName -Confirm:$false
    }
}

$Action = New-ScheduledTaskAction `
    -Execute 'powershell.exe' `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Runner`"" `
    -WorkingDirectory $ProjectRoot
$Trigger = New-ScheduledTaskTrigger -Daily -At $StartAt
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Description 'Settle results, refresh model reviews, and generate next Beijing-day World Cup forecasts at 13:00 from 2026-06-17.' `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Force

Write-Host "Installed scheduled task: $TaskName" -ForegroundColor Green
