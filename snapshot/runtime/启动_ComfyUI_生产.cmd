@echo off
"%~dp0python\python.exe" -X utf8 -B "%~dp0production_tools\launch.py" production --memory-mode original --preview-method auto --cuda-malloc --reserve-vram 4
