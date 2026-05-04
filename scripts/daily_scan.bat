@echo off
chcp 65001 > nul
setlocal

REM Swing Scanner 일일 스캔 스크립트
REM 매일 오전 7시 작업 스케줄러에 등록해 자동 실행한다.

cd /d "%~dp0.."

echo [%date% %time%] 일일 스캔 시작
python -m scanner.cli scan --market all --no-report >> logs\daily_scan.log 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [%date% %time%] 스캔 실패 (exit code: %ERRORLEVEL%)
    exit /b %ERRORLEVEL%
)

echo [%date% %time%] 리포트 생성
python -m scanner.cli report >> logs\daily_scan.log 2>&1

echo [%date% %time%] 완료
endlocal
