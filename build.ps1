$ErrorActionPreference = "Stop"

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

$venvPython = Join-Path $here ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
  $python = $venvPython
} else {
  $python = "python"
}

Write-Host "Using Python: $python"

& $python -m pip install --upgrade pip
& $python -m pip install pyinstaller

# Build the one-file windowed exe.
& $python -m PyInstaller ".\dictation.spec" --noconfirm --clean

Write-Host "Built: dist\Dictation.exe"