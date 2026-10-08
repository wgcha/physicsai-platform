@echo off
rem PhysicsAI 업데이트. 매개변수는 update.ps1로 그대로 전달(-Force 등).
rem PowerShell 7(pwsh)에서 실행해도 Windows PowerShell 5.1 기본 모듈을 쓰도록 PSModulePath 초기화
set PSModulePath=
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0update.ps1" %*
