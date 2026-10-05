@echo off
chcp 65001 >nul
if not exist "%~dp0user_data\prompt_selector\preview" mkdir "%~dp0user_data\prompt_selector\preview"
start "" "%~dp0user_data\prompt_selector\preview"
