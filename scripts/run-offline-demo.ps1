$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

python -m pipeline.generate `
    --offline `
    --target-date 2026-06-15 `
    --now 2026-06-14T18:00:00+08:00
if ($LASTEXITCODE -ne 0) { throw 'Offline generation failed.' }

npm.cmd run dev
