@echo off
rem PhysicsAI 업데이트. 매개변수는 update.ps1로 그대로 전달(-Force 등).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0update.ps1" %*
