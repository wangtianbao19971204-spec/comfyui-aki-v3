@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ============================================
echo   FFmpeg Auto-Installer for Windows
echo ============================================
echo.

REM Check if ffmpeg already exists
where ffmpeg >nul 2>&1
if %errorlevel% equ 0 (
    echo ✓ FFmpeg already installed!
    ffmpeg -version | findstr "ffmpeg version"
    echo.
    pause
    exit /b 0
)

echo FFmpeg not found. Installing...
echo.

REM Set installation directory
set INSTALL_DIR=%USERPROFILE%\ffmpeg
set BIN_DIR=%INSTALL_DIR%\bin

echo Installation directory: %INSTALL_DIR%
echo.

REM Create directory if not exists
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
if not exist "%BIN_DIR%" mkdir "%BIN_DIR%"

REM Download ffmpeg using PowerShell
echo Downloading FFmpeg essentials build...
echo This may take a few minutes...
echo.

powershell -Command "& { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; $ProgressPreference = 'SilentlyContinue'; Invoke-WebRequest -Uri 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile '%TEMP%\ffmpeg.zip' }"

if %errorlevel% neq 0 (
    echo ERROR: Download failed!
    echo Please check your internet connection.
    pause
    exit /b 1
)

echo ✓ Download completed
echo.

REM Extract using PowerShell
echo Extracting files...
powershell -Command "& { Expand-Archive -Path '%TEMP%\ffmpeg.zip' -DestinationPath '%TEMP%\ffmpeg_extract' -Force }"

if %errorlevel% neq 0 (
    echo ERROR: Extraction failed!
    pause
    exit /b 1
)

REM Find and copy ffmpeg binaries
echo Copying binaries...
for /d %%d in ("%TEMP%\ffmpeg_extract\ffmpeg-*") do (
    if exist "%%d\bin\ffmpeg.exe" (
        xcopy "%%d\bin\*.*" "%BIN_DIR%\" /Y /Q
    )
)

REM Cleanup
del "%TEMP%\ffmpeg.zip" >nul 2>&1
rmdir /s /q "%TEMP%\ffmpeg_extract" >nul 2>&1

echo ✓ Installation completed
echo.

REM Add to PATH
echo Adding to PATH...
echo.

REM Check if already in PATH
echo %PATH% | findstr /I /C:"%BIN_DIR%" >nul
if %errorlevel% equ 0 (
    echo ✓ Already in PATH
) else (
    REM Add to user PATH using PowerShell
    powershell -Command "& { $oldPath = [Environment]::GetEnvironmentVariable('Path', 'User'); $newPath = $oldPath + ';%BIN_DIR%'; [Environment]::SetEnvironmentVariable('Path', $newPath, 'User') }"
    
    if !errorlevel! equ 0 (
        echo ✓ Added to user PATH
        echo.
        echo IMPORTANT: Please restart your terminal/CMD for PATH changes to take effect!
    ) else (
        echo ✗ Failed to add to PATH automatically
        echo.
        echo Please add this path manually to your environment variables:
        echo %BIN_DIR%
    )
)

echo.
echo ============================================
echo   Installation Complete!
echo ============================================
echo.
echo FFmpeg installed to: %BIN_DIR%
echo.
echo Please RESTART your terminal/CMD and run:
echo   ffmpeg -version
echo.
pause
