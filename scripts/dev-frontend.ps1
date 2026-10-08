# Vite dev server (계약 §4.6)
$ErrorActionPreference = "Stop"
Push-Location (Join-Path $PSScriptRoot "..\frontend")
try { if (-not (Test-Path node_modules)) { npm ci }; npm run dev } finally { Pop-Location }
