$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$envFile = Join-Path $ProjectRoot '.env.local'
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^\s*([^#][^=]+)=(.*)$') {
            [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), 'Process')
        }
    }
}

python -m pipeline.settle
if ($LASTEXITCODE -ne 0) { throw 'Settlement refresh failed.' }

python -m pipeline.generate --archive
if ($LASTEXITCODE -ne 0) { throw 'Prediction pipeline failed.' }

python -m pipeline.strategy_history
if ($LASTEXITCODE -ne 0) { throw 'Strategy history refresh failed.' }

npm.cmd run build
if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }

Write-Host 'Daily prediction and static site build completed.' -ForegroundColor Green
