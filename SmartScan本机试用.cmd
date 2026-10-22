@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "SMARTSCAN_PYTHON="
if exist ".venv\Scripts\python.exe" set "SMARTSCAN_PYTHON=.venv\Scripts\python.exe"
if not defined SMARTSCAN_PYTHON where py >nul 2>nul && set "SMARTSCAN_PYTHON=py -3"
if not defined SMARTSCAN_PYTHON where python >nul 2>nul && set "SMARTSCAN_PYTHON=python"

if not defined SMARTSCAN_PYTHON (
  echo 未检测到 Python 3.11 或更高版本，请先安装 Python 后重试。
  pause
  exit /b 1
)

%SMARTSCAN_PYTHON% tools\local_trial.py menu
set "SMARTSCAN_EXIT=%ERRORLEVEL%"
echo.
pause
exit /b %SMARTSCAN_EXIT%
