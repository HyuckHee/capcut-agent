@echo off
chcp 65001 >nul
rem AI 나레이션 기능용 Claude CLI 로그인 (최초 1회만)
rem 창이 뜨면 /login 입력 → 브라우저에서 Max 구독 계정으로 로그인 → 완료 후 /exit
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
  echo Claude CLI를 찾지 못했습니다. Claude 데스크톱 앱이 설치되어 있는지 확인하세요.
  pause & exit /b 1
)
echo Claude CLI: !CC!
echo.
echo 창이 열리면  /login  을 입력해 로그인하세요. 끝나면  /exit
echo.
"!CC!"
