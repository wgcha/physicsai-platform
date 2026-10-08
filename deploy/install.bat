@echo off
rem PhysicsAI 설치(관리자 권한 PowerShell 필요). 매개변수는 install.ps1로 그대로 전달.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
