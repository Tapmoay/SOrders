"""红线：导出产物不许出现在**匿名可下载**的目录里（R12-A1 / R12-A3 / R12-A9）。

## 背景（三条缺陷连起来看）
1. **S3 那轮**把导出产物从 `/static/uploads/exports/` 挪到 `exports/`，这是对的：
   `/static/uploads/` 在生产是 nginx 用 `alias` **直出磁盘**的（请求根本不到 uvicorn），
   应用层那道 `if file_path.split("/")[0] == "exports": 404` 拦不住它。
2. 但挪得不彻底，留下两个口子（2026-09-19 审计 R12）：
   - `main.py` **每次启动都重建** `uploads/exports/` —— 等于给下一个往那儿写文件的人留了陷阱；
   - 生产 nginx 的 `location /static/uploads/` **没有** `exports/` 的 deny
     （实测：`/etc/nginx/conf.d/sorders.conf` 三处 alias，`grep exports` 零命中）。
     只要那个目录里还留着历史产物（老文件名 `ledger_{货主id}_{任务id}.xlsx`，可枚举），
     匿名就能拖走别人的账本。
3. 顺带：导出产物**从来没人清理**（`data_retention` 只清库里的表），
   于是"3 年保留"这条承诺对磁盘上的 Excel 不成立 —— 现在由 `purge_old_export_files` 管。

## 判据（清单自己算）
- 静态扫描后端源码：不允许出现"创建公开目录下的 exports 目录"的调用；
- 部署脚本里必须有那条 `location ^~ /static/uploads/exports/ → 404`；
- 保留治理里必须有导出产物的清理入口。

用法：python _tools/qa/_check_export_guards.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend/app"
DEPLOY = ROOT / "_tools/deploy"


def main() -> int:
    fails: list[str] = []

    # ① 不许再创建公开目录下的 exports/
    bad_mkdir: list[str] = []
    scanned = 0
    for f in BACKEND.rglob("*.py"):
        src = f.read_text(encoding="utf-8")
        scanned += 1
        for m in re.finditer(r"makedirs\(\s*[\"']([^\"']*exports[^\"']*)[\"']", src):
            if "uploads" in m.group(1):
                bad_mkdir.append(f"{f.relative_to(ROOT)}: {m.group(1)}")
    if scanned < 50:
        fails.append(f"只扫到 {scanned} 个后端文件——判据在空转")
    if bad_mkdir:
        fails.append("仍在创建公开静态目录下的 exports/（那是匿名可下载的）：" + "；".join(bad_mkdir))
    else:
        print(f"✅ 后端 {scanned} 个文件里没有『创建 uploads/exports』的调用")

    # ② 部署脚本必须带上 nginx 的 deny
    fix = DEPLOY / "_fix_nginx_static.py"
    src = fix.read_text(encoding="utf-8") if fix.exists() else ""
    if "/static/uploads/exports/" not in src or "return 404" not in src:
        fails.append("部署脚本没有给 /static/uploads/exports/ 加 deny（nginx 会匿名直出历史产物）")
    else:
        print("✅ 部署脚本里有 /static/uploads/exports/ → 404")

    # ③ 导出产物必须进保留治理
    retention = (BACKEND / "services/data_retention.py").read_text(encoding="utf-8")
    if "purge_old_export_files" not in retention:
        fails.append("导出产物没有清理入口（磁盘只增不减、保留承诺被绕过）")
    else:
        print("✅ 保留治理里有导出产物的清理入口")

    # ④ 产物目录与命名规则只有一处实现
    paths = (BACKEND / "services/ledger_export_paths.py").read_text(encoding="utf-8")
    for need in ("EXPORT_DIR", "LEGACY_UPLOAD_EXPORTS", "def export_file_name", "def find_export_file"):
        if need not in paths:
            fails.append(f"ledger_export_paths.py 里缺少 {need}（命名/定位又被打散了）")
    if not fails:
        print("✅ 产物目录、命名与定位规则都在 ledger_export_paths.py")

    if fails:
        print("\n❌ 导出产物的隔离/清理不完整：")
        for f in fails:
            print("   - " + f)
        return 1
    print("\n✅ 导出产物：不落公开目录、nginx 有 deny、有保留期清理、规则单点。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
