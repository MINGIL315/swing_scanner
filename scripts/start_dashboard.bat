@echo off
chcp 65001 > nul
setlocal

REM Swing Scanner 대시보드 시작 스크립트

cd /d "%~dp0.."

echo Swing Scanner 대시보드 시작 중...
echo 브라우저에서 http://127.0.0.1:8000 으로 접속하세요.
echo 종료하려면 Ctrl+C 를 누르세요.

python -m scanner.cli serve

endlocal
