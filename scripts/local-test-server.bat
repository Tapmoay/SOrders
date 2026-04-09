@echo off
REM 本地测试：启动 API 服务（默认端口 8000）
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0local-test-server.ps1"
