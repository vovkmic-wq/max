param([int]$Port = 8080)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
# Запускаем команду в локальном окружении проекта; ключи в вывод не передаём.
& .\.venv\Scripts\max-agent.exe serve --port $Port
