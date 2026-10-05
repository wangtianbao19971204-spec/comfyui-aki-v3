@echo off
chcp 65001 >nul 2>&1
call "%~dp0..\Update-SD-Trainer-Release.bat" %*
exit /b %errorlevel%
