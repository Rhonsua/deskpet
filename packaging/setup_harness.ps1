$ErrorActionPreference = 'Stop'
$project = Split-Path $PSScriptRoot -Parent
$runtime = Join-Path $project '.harness-venv'
if (-not (Test-Path (Join-Path $runtime 'Scripts/python.exe'))) {
    & (Join-Path $project '.venv/Scripts/python.exe') -m venv $runtime
    if ($LASTEXITCODE) { throw '无法创建独立工作环境' }
}
& (Join-Path $runtime 'Scripts/python.exe') -m pip install 'deepseek-harness-sdk==0.2.1rc2'
if ($LASTEXITCODE) { throw 'Harness 安装失败' }


& (Join-Path $runtime 'Scripts/python.exe') (Join-Path $PSScriptRoot 'setup_harness_approval_runtime.py')
if ($LASTEXITCODE) { throw 'Official approval runtime installation or protocol verification failed' }
