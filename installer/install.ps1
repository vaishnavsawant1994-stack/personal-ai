$ErrorActionPreference='Stop'
Set-Location (Join-Path $PSScriptRoot '..')
py -3 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\pip.exe install -r requirements.txt
& .\.venv\Scripts\python.exe -m playwright install chromium
Write-Host 'Personal AI installed. Run .\.venv\Scripts\python.exe -m app.main'
