param([int]$Port = 8080)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
& .\.venv\Scripts\max-agent.exe serve --port $Port
