@echo off
REM ============================================================
REM  CNC Access Manager - one-click launcher
REM  Double-click this file to start the server and open the app.
REM  Keep the "CNC server" window open while using the app.
REM  Close that window (or press Ctrl+C in it) to stop.
REM ============================================================
title CNC Access Manager launcher
cd /d "%~dp0"

REM Pick python launcher: prefer "py", fall back to "python"
set "PYEXE=py"
where py >nul 2>nul || set "PYEXE=python"

echo Starting CNC Access Manager with %PYEXE% ...

REM Start the server (it opens the browser automatically)
%PYEXE% server.py
