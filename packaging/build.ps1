# Builds the portable R Board zip: dist\R-Board-<version>-portable.zip
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
Write-Output $zip
