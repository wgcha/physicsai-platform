@echo off
rem PhysicsAI demo stop (double-click). Arguments are passed to stop-demo.ps1.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop-demo.ps1" %*
set PHYSICSAI_RC=%ERRORLEVEL%
if "%PHYSICSAI_NO_PAUSE%"=="" pause
exit /b %PHYSICSAI_RC%
