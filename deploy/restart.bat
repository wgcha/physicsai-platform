@echo off
rem PhysicsAI restart wrapper (double-click). Options: -Stop / -Start. Runs restart.ps1 in this folder.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0restart.ps1" %*
pause
