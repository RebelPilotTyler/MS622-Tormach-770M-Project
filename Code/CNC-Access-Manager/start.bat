@echo off
REM ============================================================
REM  CNC Access Manager - one-click launcher
REM  Double-click this file to start the server and open the app.
REM  Keep the "CNC server" window open while using the app.
REM  Close that window (or press Ctrl+C in it) to stop.
REM ============================================================
title CNC Access Manager launcher
cd /d "%~dp0"

echo Starting CNC Access Manager...

REM Start the Python server in its own window (stays open)
start "CNC server" cmd /k py server.py

REM Give the server a moment to boot, then open the browser
timeout /t 2 >nul
start "" http://localhost:8000

exit
