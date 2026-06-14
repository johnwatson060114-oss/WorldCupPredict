param(
    [switch]$NoPublish
)

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

node .\scripts\fetch-sporttery.mjs
if ($LASTEXITCODE -ne 0) {
    Write-Warning 'Sporttery browser refresh failed; the pipeline will apply its explicit fallback.'
}

python -m pipeline.settle
if ($LASTEXITCODE -ne 0) { throw 'Settlement refresh failed.' }

python -m pipeline.generate --archive
if ($LASTEXITCODE -ne 0) { throw 'Prediction pipeline failed.' }

python -m pipeline.strategy_history
if ($LASTEXITCODE -ne 0) { throw 'Strategy history refresh failed.' }

npm.cmd run build
if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }

if (-not $NoPublish) {
    git add -- public/data
    git diff --cached --quiet
    if ($LASTEXITCODE -ne 0) {
        git commit -m 'data: refresh daily forecast'
        if ($LASTEXITCODE -eq 0) {
            git push origin main
            if ($LASTEXITCODE -eq 0) {
                Write-Host 'Daily forecast pushed for GitHub Pages deployment.' -ForegroundColor Green
            } else {
                Write-Warning 'Daily forecast push failed; the 18:10 cloud fallback remains active.'
            }
        }
    }
}

Write-Host 'Daily prediction and static site build completed.' -ForegroundColor Green
