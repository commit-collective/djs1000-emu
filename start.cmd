@echo off
rem Starts the emulator and the virtual deck: see start.py.
where py >nul 2>nul
if errorlevel 1 (python "%~dp0start.py" %*) else (py -3 "%~dp0start.py" %*)
