param([switch]$Install, [int]$Port = 8000)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$dsPrefix = 'D:\conda\envs\ds-study'
if (Test-Path -LiteralPath "$dsPrefix\python.exe") {
    $dsRuntimePaths = @($dsPrefix, "$dsPrefix\Library\mingw-w64\bin", "$dsPrefix\Library\usr\bin", "$dsPrefix\Library\bin", "$dsPrefix\Scripts", "$dsPrefix\bin")
    $env:PATH = ($dsRuntimePaths -join ';') + ';' + $env:PATH
    $env:CONDA_PREFIX = $dsPrefix
    $bootstrapPython = "$dsPrefix\python.exe"
} else {
    $bootstrapPython = (Get-Command python -ErrorAction Stop).Source
}
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONPATH = Join-Path $PSScriptRoot 'src'
$mvpPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $mvpPython)) {
    & $bootstrapPython -X utf8 -m venv (Join-Path $PSScriptRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw '创建项目虚拟环境失败。' }
    $Install = $true
}
if ($Install) {
    & $mvpPython -X utf8 -m pip install -r (Join-Path $PSScriptRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw '依赖安装失败。' }
}
Write-Host "运费对账工作台：http://127.0.0.1:$Port/login"
Write-Host '管理员：admin / admin123；对账专员：recon / recon123'
& $mvpPython -X utf8 -m uvicorn freight_recon.web:app --host 127.0.0.1 --port $Port --workers 1
