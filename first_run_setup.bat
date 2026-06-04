@echo off
cd /d "%~dp0"

echo ============================================
echo   Photobooth - First Run Setup
echo ============================================
echo.

if not exist "python\python.exe" (
    echo [ERROR] python\python.exe not found.
    echo.
    echo Steps to fix:
    echo   1. Go to https://www.python.org/downloads/windows/
    echo   2. Download "Windows embeddable package (64-bit)"
    echo   3. Unzip and copy all files into the python\ folder
    echo.
    pause
    exit /b 1
)

echo [1/4] Enabling pip support...
powershell -NoProfile -Command "Get-ChildItem 'python' -Filter 'python3*._pth' | ForEach-Object { (Get-Content $_.FullName) -replace '#import site','import site' | Set-Content -Encoding ASCII $_.FullName }"
if %errorlevel% neq 0 (
    echo [ERROR] Failed to patch ._pth file.
    pause
    exit /b 1
)
echo   Done.

echo [2/4] Downloading and installing pip...
powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile 'get-pip.py'"
if not exist "get-pip.py" (
    echo [ERROR] Failed to download get-pip.py. Check network connection.
    pause
    exit /b 1
)
python\python.exe get-pip.py --quiet
del get-pip.py
echo   Done.

echo [3/4] Installing dependencies...
python\python.exe -m pip install -r backend\requirements.txt --no-warn-script-location
if %errorlevel% neq 0 (
    echo [ERROR] Dependency installation failed. See above for details.
    pause
    exit /b 1
)
echo   Done.

echo.
echo ============================================
echo   [4/4] Clear previous session data?
echo ============================================
echo   Select Y if you are setting up a new PC
echo   and want to start fresh. This will clear:
echo     - LINE BOT settings
echo     - All photos, thumbnails and pickup codes
echo     - Background image and homepage text settings
echo     - Gallery config (enable/watermark)
echo     - Custom uploaded fonts
echo     - ngrok Auth Token
echo     - Admin accounts (reset to admin/admin)
echo.
echo   Select N to keep existing data.
echo ============================================
echo.
choice /c YN /m "Clear previous data"
if %errorlevel%==1 goto :clear_data
goto :setup_done

:clear_data
echo.
echo Clearing previous session data...
if exist "backend\storage\line_config.json"    del /f /q "backend\storage\line_config.json"
if exist "backend\storage\ngrok_config.json"   del /f /q "backend\storage\ngrok_config.json"
if exist "backend\storage\accounts.json"       del /f /q "backend\storage\accounts.json"
if exist "backend\storage\gallery_config.json" del /f /q "backend\storage\gallery_config.json"
if exist "backend\storage\index_text.json"     del /f /q "backend\storage\index_text.json"
if exist "backend\storage\fonts_meta.json"     del /f /q "backend\storage\fonts_meta.json"
if exist "backend\storage\bg\bg.jpg"           del /f /q "backend\storage\bg\bg.jpg"
if exist "backend\storage\bg\bg.webp"          del /f /q "backend\storage\bg\bg.webp"
del /f /q "backend\storage\incoming\*.jpg"     2>nul
del /f /q "backend\storage\incoming\*.jpeg"    2>nul
del /f /q "backend\storage\incoming\*.png"     2>nul
del /f /q "backend\storage\thumbs\*"           2>nul
del /f /q "backend\storage\fonts\*"            2>nul
powershell -NoProfile -Command "[IO.File]::WriteAllText([IO.Path]::GetFullPath('backend\storage\photo_codes.json'), '{}')"
echo   Done. Admin account will be reset to admin / admin on first launch.

:setup_done
echo.
echo ============================================
echo   Setup complete! Run start.bat to launch.
echo ============================================
echo.
pause
