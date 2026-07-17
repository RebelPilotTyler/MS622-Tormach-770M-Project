@echo off
REM ============================================================
REM  Build a standalone Windows .exe of the CNC Access Manager.
REM  Run this ONCE on a PC that has Python. The resulting app
REM  needs NO Python to run on the school computer.
REM ============================================================
title Build CNC Access Manager (.exe)
cd /d "%~dp0"

set "PYEXE=py"
where py >nul 2>nul || set "PYEXE=python"

echo Installing PyInstaller (one time)...
%PYEXE% -m pip install --user pyinstaller || goto :err

echo.
echo Building CNC-Access-Manager.exe ...
%PYEXE% -m PyInstaller --onefile --noconfirm --name CNC-Access-Manager server.py || goto :err

echo.
echo Assembling the portable folder...
if not exist "portable" mkdir "portable"
copy /y "dist\CNC-Access-Manager.exe" "portable\" >nul
copy /y index.html "portable\" >nul
copy /y style.css  "portable\" >nul
copy /y app.js     "portable\" >nul
copy /y cnc.db     "portable\" >nul 2>nul

echo.
echo ============================================================
echo  DONE.  Copy the whole "portable" folder to the school PC
echo  and double-click  CNC-Access-Manager.exe  (no Python needed).
echo ============================================================
pause
exit /b 0

:err
echo.
echo Build failed. Make sure Python is installed and on PATH.
pause
exit /b 1
