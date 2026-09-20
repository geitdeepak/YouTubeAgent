<#
.SYNOPSIS
    Registers a Windows Task Scheduler task that runs `edutube daily` once a day
    (LLR-SCH-01).

.DESCRIPTION
    Creates (or replaces) a scheduled task named "EduTube Daily" that runs the
    project's virtual-environment Python with `-m edutube.cli daily`, working
    directory set to the project root, at the time configured in config.yaml
    (schedule.run_time), or an explicit -RunTime override.

.PARAMETER RunTime
    Time of day to run, e.g. "06:00". Defaults to the project's
    config.yaml -> schedule.run_time, or 06:00 if that cannot be read.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\schedule_windows.ps1
    powershell -ExecutionPolicy Bypass -File scripts\schedule_windows.ps1 -RunTime 07:30
#>

param(
    [string]$RunTime
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$ConfigPath = Join-Path $ProjectRoot "config.yaml"

if (-not (Test-Path $VenvPython)) {
    Write-Error "Virtual environment not found at $VenvPython. Run: python -m venv .venv; pip install -e `".[dev]`""
    exit 1
}

if (-not $RunTime) {
    $RunTime = "06:00"
    if (Test-Path $ConfigPath) {
        $match = Select-String -Path $ConfigPath -Pattern "run_time:\s*['""]?(\d{2}:\d{2})" | Select-Object -First 1
        if ($match) { $RunTime = $match.Matches[0].Groups[1].Value }
    }
}

$TaskName = "EduTube Daily"
$Action = New-ScheduledTaskAction -Execute $VenvPython -Argument "-m edutube.cli daily" -WorkingDirectory $ProjectRoot
$Trigger = New-ScheduledTaskTrigger -Daily -At $RunTime
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings `
    -Description "Runs 'edutube daily' to generate and upload scheduled AI-education videos." | Out-Null

Write-Host "Registered scheduled task '$TaskName' to run daily at $RunTime."
Write-Host "View it with: Get-ScheduledTask -TaskName '$TaskName'"
Write-Host "Remove it with: Unregister-ScheduledTask -TaskName '$TaskName'"
