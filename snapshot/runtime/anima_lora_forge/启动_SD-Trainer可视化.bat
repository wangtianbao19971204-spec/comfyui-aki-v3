@echo off
chcp 65001 >nul
powershell -NoProfile -Command "try { $r=Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://127.0.0.1:28000; if($r.StatusCode -eq 200){exit 0} }; exit 1" >nul 2>&1
if not errorlevel 1 (
    start "" "http://127.0.0.1:28000"
    exit /b 0
)
call "%~dp0vendor\sd-trainer\run_gui.bat"
