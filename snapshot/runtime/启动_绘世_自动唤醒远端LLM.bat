@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
rem Local JSON: COMFYUI_EXTERNAL_ROOT/private-config/remote-llm/config.json
"%~dp0python\python.exe" -X utf8 -B "%~dp0remote_llm_guard\launcher.py" start
set "COMFY_LAUNCH_EXIT=%errorlevel%"
pause
exit /b %COMFY_LAUNCH_EXIT%
