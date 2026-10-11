param([int]$Port = 0)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
# Запускаем команду в локальном окружении проекта; ключи в вывод не передаём.
if ($Port) { & .\.venv\Scripts\max-agent.exe serve --port $Port } else { & .\.venv\Scripts\max-agent.exe serve }
