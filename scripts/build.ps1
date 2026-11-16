$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Icon = Join-Path $ProjectRoot "resources\xray-ui.ico"
$Resource = Join-Path $ProjectRoot "resources"
$Launcher = Join-Path $ProjectRoot "run_xray_ui.py"
$Source = Join-Path $ProjectRoot "src"
$BasePrefix = (& $Python -c "import sys; print(sys.base_prefix)").Trim()
$RuntimeBin = Join-Path $BasePrefix "Library\bin"
$BinaryArgs = @()
foreach ($Name in @("libcrypto-3-x64.dll", "libssl-3-x64.dll", "liblzma.dll", "libbz2.dll")) {
    $Path = Join-Path $RuntimeBin $Name
    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        $BinaryArgs += @("--add-binary", "$Path;.")
    }
}

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --noconsole `
    --name XrayUI `
    --icon $Icon `
    --paths $Source `
    --add-data "$Resource;resources" `
    --exclude-module PySide6.QtWebEngineCore `
    --exclude-module PySide6.QtWebEngineWidgets `
    --exclude-module PySide6.QtWebEngineQuick `
    @BinaryArgs `
    $Launcher

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller 打包失败"
}

Write-Output (Join-Path $ProjectRoot "dist\XrayUI.exe")
