@echo off
chcp 65001 >nul
rem 윈도우용 실행 래퍼 — 더블클릭하면 run.py가 나머지를 처리한다.
cd /d "%~dp0"
where py >nul 2>nul && (py -3 run.py) || (python run.py)
pause
