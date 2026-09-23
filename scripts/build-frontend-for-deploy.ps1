# 生产前端构建：在仓库根目录使用与 Vite 一致的 envDir（根目录 .env 中 VITE_*）
# 用法：在仓库根目录执行  .\scripts\build-frontend-for-deploy.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Frontend = Join-Path $Root "frontend"
if (-not (Test-Path (Join-Path $Frontend "package.json"))) {
    Write-Error "未找到 frontend\package.json，请在仓库根目录运行本脚本。"
}
Set-Location $Frontend
npm ci
npm run build
Write-Host "构建完成: $(Join-Path $Root 'frontend\dist')" -ForegroundColor Green
