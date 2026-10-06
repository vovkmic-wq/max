param([string]$Python = 'py')
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    if ($Python -eq 'py') { & py -3.12 -m venv .venv } else { & $Python -m venv .venv }
    if ($LASTEXITCODE -ne 0) { throw 'Python environment creation failed' }
}
& .\.venv\Scripts\python.exe -m pip install -r requirements.lock
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
& .\.venv\Scripts\python.exe -m pip install --no-deps -e .
if ($LASTEXITCODE -ne 0) { throw 'Application installation failed' }
& .\.venv\Scripts\max-agent.exe init
if ($LASTEXITCODE -ne 0) { throw 'Initialization failed' }
npm.cmd ci --ignore-scripts --no-audit --no-fund
if ($LASTEXITCODE -ne 0) { throw 'OpenCode installation failed' }
npm.cmd rebuild @opencode/cli --foreground-scripts
if ($LASTEXITCODE -ne 0) { throw 'OpenCode binary preparation failed' }
