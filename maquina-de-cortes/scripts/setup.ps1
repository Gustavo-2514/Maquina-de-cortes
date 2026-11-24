# Instala a Máquina de Cortes no Windows (PowerShell). NÃO TESTADO — o desenvolvimento foi feito no Linux.
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 [-SemModelos]
param([switch]$SemModelos)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

function Need($cmd, $wingetId, $nome) {
  if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
    Write-Host "  -> instalando $nome via winget..."
    winget install --id $wingetId -e --accept-source-agreements --accept-package-agreements
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
  }
  Write-Host "  OK $nome"
}

Write-Host "1/5 Ferramentas"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"
  $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}
Need ffmpeg "Gyan.FFmpeg" "FFmpeg"
Need node "OpenJS.NodeJS.LTS" "Node.js"
Need ollama "Ollama.Ollama" "Ollama"

Write-Host "2/5 Ambiente Python (.venv)"
if (-not (Test-Path ".venv\Scripts\python.exe")) { uv venv --python 3.12 .venv }
uv pip install --python .venv\Scripts\python.exe -r backend\requirements.txt

Write-Host "3/5 Interface"
Push-Location frontend; npm ci --no-audit --no-fund; npm run build; Pop-Location

Write-Host "4/5 Modelos de IA"
if (-not $SemModelos) { .venv\Scripts\python.exe run.py --baixar-modelos }

Write-Host "5/5 Diagnostico"
.venv\Scripts\python.exe run.py --diagnostico
Write-Host "`nPronto! Para abrir: scripts\start.bat"
