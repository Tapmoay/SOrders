#!/usr/bin/env bash
# 在仓库根目录加载 .env（Vite 从根目录读 VITE_*），构建前端到 frontend/dist。
# 用法：bash deploy/build-frontend.sh（在仓库根目录执行，或任意目录传入仓库根为第一个参数）

set -euo pipefail

ROOT="${1:-}"
if [[ -z "${ROOT}" ]]; then
  ROOT="$(cd "$(dirname "$0")/.." && pwd)"
fi

if [[ ! -f "${ROOT}/frontend/package.json" ]]; then
  echo "未找到 frontend/package.json，请传入正确的仓库根路径。" >&2
  exit 1
fi

cd "${ROOT}/frontend"
npm ci
npm run build
echo "构建完成: ${ROOT}/frontend/dist"
