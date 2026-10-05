@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0.."
echo Updating Python dependencies...
"python_embeded\python.exe" -s -m pip install --upgrade torch torchvision --index-url https://download.pytorch.org/whl/cu128
"python_embeded\python.exe" -s -m pip install --upgrade -r "SD-Trainer\requirements.txt"
echo Done.
pause
