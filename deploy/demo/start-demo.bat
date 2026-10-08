@echo off
rem PhysicsAI demo start (double-click). Arguments are passed to start-demo.ps1.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-demo.ps1" %*
set PHYSICSAI_RC=%ERRORLEVEL%
if "%PHYSICSAI_NO_PAUSE%"=="" pause
exit /b %PHYSICSAI_RC%
