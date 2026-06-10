@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

cd /d "%~dp0"

:: ── Resolve Node.js ──
set NODE=
for /f "delims=" %%i in ('where node 2^>nul') do set NODE=%%i & goto :found_system
:found_system
if defined NODE goto :run

:: Check bundled runtime
if exist "app\runtime\node-win-x64\node.exe" set NODE=%~dp0app\runtime\node-win-x64\node.exe & goto :run

echo [ERROR] Node.js not found. Install Node.js >= 22 or download the full package.
exit /b 1

:run
set ENGINE_DIR=app\core\node_modules\openclaw
set OPENCLAW_MJS=%ENGINE_DIR%\openclaw.mjs
set DATA_DIR=data\.openclaw
set CONFIG_FILE=%DATA_DIR%\openclaw.json

if not exist "%OPENCLAW_MJS%" (
    echo [ERROR] Engine not found at %OPENCLAW_MJS%
    exit /b 1
)

set OPENCLAW_NO_AUTO_UPDATE=true
set OPENCLAW_HOME=%~dp0%DATA_DIR%
set OPENCLAW_STATE_DIR=%~dp0%DATA_DIR%\.openclaw

if "%1"=="" (
    :: Default: open starter page
    python "%~dp0webui\server.py" --port 3131 2>nul
    start http://localhost:3131/starter
    goto :eof
)

if "%1"=="webui" (
    python "%~dp0webui\server.py" --port %2
    goto :eof
)

if "%1"=="config" (
    python "%~dp0webui\server.py" --port 3131 2>nul
    start http://localhost:3131/starter
    goto :eof
)

if "%1"=="status" (
    echo OpenClaw Windows Edition
    %NODE% --version 2>nul
    dir "%ENGINE_DIR%" >nul 2>&1 && echo Engine: installed || echo Engine: NOT FOUND
    goto :eof
)

if "%1"=="help" (
    echo OpenClaw -- Multi-channel AI Gateway
    echo.
    echo Usage:
    echo   openclaw                   Open config page in browser
    echo   openclaw webui [port]      Start Web UI
    echo   openclaw status            Show system status
    echo   openclaw gateway run       Start the Gateway
    echo   openclaw help              Show this help
    goto :eof
)

:: Pass through to CLI
%NODE% "%OPENCLAW_MJS%" %*
