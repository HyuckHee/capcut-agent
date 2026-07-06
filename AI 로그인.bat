@echo off
rem One-time Claude CLI login for the AI draft feature.
rem When the prompt opens: type /login , sign in with your Max account, then /exit
setlocal enabledelayedexpansion
set "CC="
for /f "delims=" %%d in ('dir /b /ad /o-n "%APPDATA%\Claude\claude-code" 2^>nul') do (
  if not defined CC set "CC=%APPDATA%\Claude\claude-code\%%d\claude.exe"
)
if not defined CC for /d %%p in ("%LOCALAPPDATA%\Packages\Claude_*") do (
  for /f "delims=" %%d in ('dir /b /ad /o-n "%%p\LocalCache\Roaming\Claude\claude-code" 2^>nul') do (
    if not defined CC set "CC=%%p\LocalCache\Roaming\Claude\claude-code\%%d\claude.exe"
  )
)
if not defined CC (
  echo Claude CLI not found. Install or launch the Claude desktop app first.
  pause
  exit /b 1
)
echo Claude CLI: !CC!
echo.
echo Type /login to sign in with your Max account. When finished, type /exit
echo.
"!CC!"
echo.
pause
