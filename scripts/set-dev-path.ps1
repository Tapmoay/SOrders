# 将仓库内便携 Node.js（若已解压到 .tools）加入当前会话 PATH，便于 npm / Vite 找到 node。
# 用法：在 PowerShell 中先执行：  . D:\...\SOrders\scripts\set-dev-path.ps1

$root = Split-Path $PSScriptRoot -Parent
$nodeDir = Get-ChildItem "$root\.tools\node-*-win-x64" -Directory -ErrorAction SilentlyContinue | Select-Object -First 1
if ($nodeDir) {
    $env:Path = "$($nodeDir.FullName);$env:Path"
    Write-Host "OK: Node on PATH -> $($nodeDir.FullName)"
    & node --version
} else {
    Write-Host "No portable Node under .tools. Install Node 20+ from https://nodejs.org/ or run: winget install OpenJS.NodeJS.LTS --source winget"
}
