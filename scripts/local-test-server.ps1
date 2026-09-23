# 本地测试：启动 SOrders API（FastAPI + Socket.IO），默认 http://127.0.0.1:8000
# 用法：在仓库根目录执行  .\scripts\local-test-server.ps1
# 依赖：已安装 backend/requirements.txt；仓库根目录 .env 中 DATABASE_URL 等

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $Root "backend\app\main.py"))) {
    Write-Error "未找到 backend\app\main.py，请在仓库根目录下运行 scripts\local-test-server.ps1"
}
Set-Location (Join-Path $Root "backend")

Write-Host "SOrders API — 工作目录: $(Get-Location)" -ForegroundColor Cyan
Write-Host "健康检查: GET http://127.0.0.1:8000/health" -ForegroundColor DarkGray
Write-Host "API 前缀: http://127.0.0.1:8000/api/v1" -ForegroundColor DarkGray
Write-Host "按 Ctrl+C 停止`n" -ForegroundColor DarkGray

python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
