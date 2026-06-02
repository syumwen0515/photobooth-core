@echo off
cd /d "%~dp0"

if not exist "python\python.exe" (
    echo [ERROR] Python runtime not found.
    echo Please run first_run_setup.bat first.
    pause
    exit /b 1
)

echo ============================================
echo   Photobooth Backend
echo ============================================
echo.
echo Open browser at: http://localhost:8000
echo Press Ctrl+C to stop.
echo ============================================
echo.

cd backend
..\python\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
cd /d "%~dp0"

echo.
echo Server stopped.
pause
