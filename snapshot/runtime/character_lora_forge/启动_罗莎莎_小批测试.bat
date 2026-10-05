@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File ".\运行_角色炼制.ps1" -Action run -Limit 2
echo.
echo 小批测试结束。请查看 characters\rosasha\runs 下最新目录中的 review.html。
pause
