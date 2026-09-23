# 本地测试：启动 Vue + Vite 前端（默认 http://127.0.0.1:5173，代理 /api 到 8000）
# 请先另开终端运行 scripts\local-test-server.ps1 启动 API
# 用法：.\scripts\local-frontend-dev.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location (Join-Path $Root "frontend")
Write-Host "SOrders Frontend — $(Get-Location)" -ForegroundColor Cyan
Write-Host "浏览器: http://127.0.0.1:5173/`n" -ForegroundColor DarkGray
npm run dev
