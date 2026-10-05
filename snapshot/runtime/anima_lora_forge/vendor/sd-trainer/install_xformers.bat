@echo off
chcp 65001 >nul 2>&1
title Install xformers
cd /d "%~dp0"
set "PYTHON_EXE=%~dp0python_embeded\python.exe"
if not exist "%PYTHON_EXE%" (
    echo [ERROR] python_embeded\python.exe not found!
    pause
    exit /b 1
)
echo.
echo  Installing xformers 0.0.30 for Torch 2.7.0 + CUDA 12.8 ...
echo.
"%PYTHON_EXE%" -s -m pip install xformers==0.0.30 --index-url https://download.pytorch.org/whl/cu128 --no-warn-script-location
if errorlevel 1 (
    echo [ERROR] xformers installation failed.
    pause
    exit /b 1
)
echo.
echo  Verifying...
"%PYTHON_EXE%" -s -c "import xformers; print(f'  xformers {xformers.__version__} OK')"
echo.
echo  Done! You can now use attn_mode = xformers.
echo.
pause
