@echo off
rem PhysicsAI 설치(관리자 권한 PowerShell 필요). 매개변수는 install.ps1로 그대로 전달.
rem PowerShell 7(pwsh)에서 실행해도 Windows PowerShell 5.1 기본 모듈을 쓰도록 PSModulePath 초기화
set PSModulePath=
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
