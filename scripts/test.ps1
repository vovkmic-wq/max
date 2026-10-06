$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
New-Item -ItemType Directory -Path .test-state -Force | Out-Null
& .\.venv\Scripts\ruff.exe check src tests scripts
if ($LASTEXITCODE -ne 0) { throw 'Lint failed' }
& .\.venv\Scripts\python.exe -m pytest --basetemp=.test-state\pytest --junitxml=docs\research\tests.xml --cov=max_channel_agent --cov-report=term-missing
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
& .\.venv\Scripts\python.exe -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Dependency check failed' }
