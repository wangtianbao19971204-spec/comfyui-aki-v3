@echo off
setlocal
REM Danbooru Browser Bridge helper for ComfyUI-Danbooru-Gallery v12.
REM Change PROXY_SERVER if your proxy port is different. Leave it empty to use Chrome/system defaults.
set PROXY_SERVER=http://127.0.0.1:10081
set DEBUG_PORT=9222
set PROFILE_DIR=%LOCALAPPDATA%\DanbooruBridgeChrome

set CHROME_EXE=
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set CHROME_EXE=%ProgramFiles%\Google\Chrome\Application\chrome.exe
if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set CHROME_EXE=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe
if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" set CHROME_EXE=%LocalAppData%\Google\Chrome\Application\chrome.exe

if "%CHROME_EXE%"=="" (
  echo Chrome not found. Edit this file and set CHROME_EXE manually, or use Edge with remote debugging.
  pause
  exit /b 1
)

if not exist "%PROFILE_DIR%" mkdir "%PROFILE_DIR%"

echo Starting Chrome with remote debugging on 127.0.0.1:%DEBUG_PORT%
echo Profile: %PROFILE_DIR%
if "%PROXY_SERVER%"=="" (
  start "Danbooru Bridge Chrome" "%CHROME_EXE%" --remote-debugging-address=127.0.0.1 --remote-debugging-port=%DEBUG_PORT% --remote-allow-origins=* --user-data-dir="%PROFILE_DIR%" "https://danbooru.donmai.us/posts.json?limit=1"
) else (
  echo Proxy: %PROXY_SERVER%
  start "Danbooru Bridge Chrome" "%CHROME_EXE%" --remote-debugging-address=127.0.0.1 --remote-debugging-port=%DEBUG_PORT% --remote-allow-origins=* --user-data-dir="%PROFILE_DIR%" --proxy-server="%PROXY_SERVER%" "https://danbooru.donmai.us/posts.json?limit=1"
)
endlocal
