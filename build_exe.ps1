$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

python -m pip install pyinstaller

python -m PyInstaller `
  --clean `
  --onefile `
  --name TikTok_BD_Auto `
  main2.py

$packageDir = Join-Path $projectRoot "release\TikTok_BD_Auto"
New-Item -ItemType Directory -Force -Path $packageDir | Out-Null
Remove-Item (Join-Path $packageDir "auth_config.json") -Force -ErrorAction SilentlyContinue
Copy-Item "dist\TikTok_BD_Auto.exe" $packageDir -Force
Copy-Item "config.example.json" (Join-Path $packageDir "config.example.json") -Force
Copy-Item "auth_config.example.json" (Join-Path $packageDir "auth_config.example.json") -Force
Copy-Item "requirements.txt" $packageDir -Force
Copy-Item "AUTHORIZATION.md" $packageDir -Force

New-Item -ItemType Directory -Force -Path (Join-Path $packageDir "images") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $packageDir "logs") | Out-Null
Copy-Item "images\template_notes.txt" (Join-Path $packageDir "images\template_notes.txt") -Force

$zipPath = Join-Path $projectRoot "release\TikTok_BD_Auto.zip"
Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
Compress-Archive -Path (Join-Path $packageDir "*") -DestinationPath $zipPath -Force

Write-Host "Release package created:"
Write-Host $packageDir
Write-Host $zipPath
