# Swing Scanner — Windows 작업 스케줄러 등록 스크립트
# 관리자 권한으로 실행 필요
# 사용법: powershell -ExecutionPolicy Bypass -File setup_scheduler.ps1

param(
    [string]$Time = "07:00",
    [string]$TaskName = "SwingScanner-DailyScan"
)

$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$BatPath     = Join-Path $ScriptDir "daily_scan.bat"
$LogDir      = Join-Path $ProjectRoot "logs"

if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

$Action  = New-ScheduledTaskAction -Execute $BatPath -WorkingDirectory $ProjectRoot
$Trigger = New-ScheduledTaskTrigger -Daily -At $Time
$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -RestartCount 1 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -StartWhenAvailable

try {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action   $Action `
        -Trigger  $Trigger `
        -Settings $Settings `
        -RunLevel Highest `
        -Force | Out-Null

    Write-Host "작업 스케줄러 등록 완료: $TaskName" -ForegroundColor Green
    Write-Host "실행 시각: 매일 $Time" -ForegroundColor Cyan
    Write-Host "로그 경로: $LogDir\daily_scan.log" -ForegroundColor Cyan
} catch {
    Write-Host "등록 실패: $_" -ForegroundColor Red
    exit 1
}
