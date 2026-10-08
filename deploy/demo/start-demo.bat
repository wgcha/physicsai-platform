@echo off
rem PhysicsAI demo start (double-click). Arguments are passed to start-demo.ps1.
rem Reset PSModulePath so Windows PowerShell 5.1 loads its own modules even when called from pwsh 7.
set PSModulePath=
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-demo.ps1" %*
set PHYSICSAI_RC=%ERRORLEVEL%
if "%PHYSICSAI_NO_PAUSE%"=="" pause
exit /b %PHYSICSAI_RC%
