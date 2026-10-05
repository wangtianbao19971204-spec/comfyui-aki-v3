@echo off
setlocal enabledelayedexpansion

:: Check if ffmpeg is available
where ffmpeg >nul 2>nul
if %errorlevel% neq 0 (
    echo Error: ffmpeg is not found in PATH.
    echo Please install ffmpeg or add it to your PATH.
    pause
    exit /b 1
)

:: Get input file from argument or prompt
set "INPUT_FILE=%~1"
if "%INPUT_FILE%"=="" (
    set /p "INPUT_FILE=Drag and drop the MP3 file here or paste the path: "
)

:: Remove quotes from input if present (in case of paste)
set "INPUT_FILE=%INPUT_FILE:"=%"

:: Check if file exists
if not exist "%INPUT_FILE%" (
    echo Error: File "%INPUT_FILE%" not found.
    pause
    exit /b 1
)

:: Get file info
for %%F in ("%INPUT_FILE%") do (
    set "FILENAME=%%~nF"
    set "FILEDIR=%%~dpF"
    set "EXT=%%~xF"
)

:: Create output folder
set "OUT_DIR=%FILEDIR%%FILENAME%_parts"
if not exist "%OUT_DIR%" mkdir "%OUT_DIR%"

:: Get split duration from user
set /p "SPLIT_SEC=Enter number of seconds per segment (e.g. 150 for 2m30s): "
if "%SPLIT_SEC%"=="" set "SPLIT_SEC=150"

echo Splitting "%INPUT_FILE%" into %SPLIT_SEC%s chunks...

:: ffmpeg command to split
:: -f segment: use segment muxer
:: -c copy: copy stream without re-encoding (fastest)
ffmpeg -i "%INPUT_FILE%" -f segment -segment_time %SPLIT_SEC% -segment_start_number 1 -c copy "%OUT_DIR%\%FILENAME%_%%03d.mp3"

if %errorlevel% equ 0 (
    echo.
    echo Done! Files saved in: "%OUT_DIR%"
) else (
    echo.
    echo An error occurred during splitting.
)

pause
