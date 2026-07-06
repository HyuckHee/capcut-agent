@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo   캡컷 에이전트 시작 중... 브라우저가 곧 열립니다.
echo   (이 창을 닫으면 서버가 종료됩니다)
echo.
start "" http://localhost:8765
.venv\Scripts\python.exe -m uvicorn web.server:app --port 8765 --app-dir "%~dp0"
pause
