@echo off
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0运行_Anima_LoRA.ps1" -Action doctor -Profile "profiles\rosasha.json"
pause

