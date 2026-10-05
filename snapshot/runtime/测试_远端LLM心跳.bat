@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
rem Foreground heartbeat loop; Ctrl+C stops only this test client.
"%~dp0python\python.exe" -X utf8 -B "%~dp0remote_llm_guard\launcher.py" heartbeat
set "COMFY_HEARTBEAT_EXIT=%errorlevel%"
pause
exit /b %COMFY_HEARTBEAT_EXIT%
