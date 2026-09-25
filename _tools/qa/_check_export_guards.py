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

import ast
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
#: 复用单源红线里的 code_only（剥注释与字符串常量、保留行号）。
from _check_single_source import code_only  # noqa: E402


def _live_strings(path: Path) -> str:
    """文件里**真的会执行的**字符串字面量（⛔ 不含文档字符串）。

    为什么要它：判据原来只做「某个字符串在不在这份源码里」，而**文档字符串里也写着同一段
    nginx 片段** —— 把真正要写进 conf 的那一份删掉，判据照样绿（2026-09-25 反向验证当场抓到）。
    注释天然不在 AST 里，所以排除文档字符串就够了。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                docs.add(id(body[0].value))
    return chr(10).join(
        n.value for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs
    )

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
    # ⛔ 2026-09-25 改硬：① 只看**真的会执行的字符串**（文档字符串里也写着同一段片段）；
    #    ② deny 片段必须出现**两次** —— 这个脚本有两条路（新机器用 NEW_BLOCK、老机器用 re.subn 插），
    #       少任何一条，走那条路的机器就仍然匿名可下载（判据说「有 deny」而实际只修了一半）。
    live = _live_strings(fix) if fix.exists() else ""
    n_deny = len(re.findall(r"location \^~ /static/uploads/exports/", live))
    if "return 404" not in live or n_deny < 2:
        fails.append(
            "部署脚本没有给 /static/uploads/exports/ 加 deny（要在**两条路**上都带：新机器的 "
            "NEW_BLOCK + 老机器的 re.subn 插入；当前认出 " + str(n_deny) + " 处）—— "
            "nginx 会匿名直出历史产物"
        )
    else:
        print("✅ 部署脚本的两条路都带 /static/uploads/exports/ → 404")

    # ③ 导出产物必须进保留治理
    # ⛔ 判在 code_only 上：注释里写着那一行**不算**「挂上了」—— 2026-09-25 反向验证第 ③ 条实测：
    #    把任务表那一行注释掉，判据照样绿（注释里仍然有 , purge_old_export_files) 这几个字符）。
    retention = code_only((BACKEND / "services/data_retention.py").read_text(encoding="utf-8"))
    # ⛔ 2026-09-25：原来只查 `"purge_old_export_files" not in retention` —— 那**一个定义就够了**：
    #    把函数删掉不算，**只把任务表里那一行删掉**（函数还在、没人调它）判据照样绿，
    #    而真实后果是导出产物**永远不会被清理**（磁盘只增不减、保留承诺被绕过）。
    #    所以现在要两件：**有实现** + **真的挂进每日任务表**（锚在调用形状上，不是名字上 ——
    #    「判据被自己的文档满足」这在本项目已经栽过 4 次）。
    if "def purge_old_export_files(" not in retention:
        fails.append("导出产物没有清理实现（磁盘只增不减、保留承诺被绕过）")
    elif ", purge_old_export_files)" not in retention:
        fails.append(
            "导出产物的清理**没有挂进每日任务表**（函数在、但没人调它 = 永远不会跑）—— "
            "在 data_retention 的任务元组里补一行 (\"exports_purged\", purge_old_export_files)"
        )
    else:
        print("✅ 保留治理里有导出产物的清理实现，而且真的挂进了任务表")

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
