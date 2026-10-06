# Builds the portable R Board zip, dist\R-Board-<version>-portable.zip,
# and the AI features plugin, dist\R-Board-AI-<version>.zip.
# Used locally (.\packaging\build.ps1 -Python .venv\Scripts\python.exe)
# and by the release workflow on GitHub (.github\workflows\release.yml).
param([string]$Python = "python")
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

$version = (& $Python -c "from beeref import constants; print(constants.VERSION)").Trim()
$app = "dist\R Board"

if (Test-Path build) { Remove-Item build -Recurse -Force }
if (Test-Path $app) { Remove-Item $app -Recurse -Force }
& $Python -m PyInstaller RBoard.spec --noconfirm --log-level WARN
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

(Get-Content "packaging\READ ME.txt" -Raw).Replace("{version}", $version) |
    Set-Content "$app\READ ME.txt" -Encoding utf8
Copy-Item LICENSE "$app\LICENSE.txt"

$zip = "dist\R-Board-$version-portable.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path $app -DestinationPath $zip -CompressionLevel Optimal

# AI features plugin: its code plus onnxruntime and tokenizers in lib\,
# for the Python version the app is built with
$ai = "build\ai-plugin"
New-Item -ItemType Directory $ai | Out-Null
Copy-Item plugins\ai\rboard_ai.py $ai
$manifest = Get-Content plugins\ai\plugin.json -Raw | ConvertFrom-Json
$manifest.version = $version
$manifest.python = (& $Python -c "import sys; print(f'cp{sys.version_info[0]}{sys.version_info[1]}')").Trim()
# No BOM: the app reads plugin.json as plain UTF-8
[IO.File]::WriteAllText("$PWD\$ai\plugin.json", ($manifest | ConvertTo-Json))
Copy-Item LICENSE "$ai\LICENSE.txt"
& $Python -m pip install --quiet --no-deps --only-binary=:all: --target "$ai\lib" "onnxruntime>=1.20" "tokenizers>=0.20"
if ($LASTEXITCODE -ne 0) { throw "pip failed" }
# Model-conversion tools and command-line scripts the app never uses
foreach ($extra in "bin", "onnxruntime\tools", "onnxruntime\transformers", "onnxruntime\quantization") {
    if (Test-Path "$ai\lib\$extra") { Remove-Item "$ai\lib\$extra" -Recurse -Force }
}
$aiZip = "dist\R-Board-AI-$version.zip"
if (Test-Path $aiZip) { Remove-Item $aiZip }
Compress-Archive -Path "$ai\*" -DestinationPath $aiZip -CompressionLevel Optimal

Write-Output $zip
Write-Output $aiZip
