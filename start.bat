@echo off
chcp 65001 >nul
title Albion Black Market Flipper
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
  echo.
  echo   Python is not installed.
  echo   Download it from https://www.python.org/downloads/
  echo   and tick "Add python.exe to PATH" during setup, then run this file again.
  echo.
  start https://www.python.org/downloads/
  pause
  exit /b 1
)

rem The Albion Data Client needs Npcap to read the game's market data.
if not exist "%SystemRoot%\System32\wpcap.dll" if not exist "%SystemRoot%\System32\Npcap\wpcap.dll" (
  echo.
  echo   Npcap is not installed - the live market capture needs it.
  echo   Download the installer from https://npcap.com/#download
  echo   and tick "Install Npcap in WinPcap API-compatible Mode" during setup.
  echo   The tool still starts now, but without your own market scans.
  echo.
  start https://npcap.com/#download
  pause
)

python server.py
pause
