# -*- coding: utf-8 -*-
"""R4-06 的 **Remove 演练**：完整拆掉一个扩展，核心照样成立。

## 指南 §24 把"拆除"拆成**四件不同的事**，这个演练一件一件做

| 步 | 做什么 | 怎么判 |
| --- | --- | --- |
| 1 停用 Disable | 清单里 enabled=False | 路由消失、核心照常；**代码还在** |
| 2 卸载 Uninstall | 目录移出仓库 | 注册表里没有它了；静态检查不许出现 orphan import / config |
| 3 删代码 Code Removal | 全量静态检查 + core smoke | 全绿 |
| 4 数据 Data Removal | 它 owns_tables=() | **没有数据要删** —— 核心事实表一张不少 |

## 为什么第 4 步是这条演练最想证的事

指南 §24 原话：「**扩展被删除，不代表它创造的历史事实可以删除**」。
本项目的落地方式是"扩展不拥有任何核心事实"：

* 扩展的 owns_tables 是空的（判据 _check_data_ownership.py 核）；
* 订单在派单那一刻把规则**定格**进 orders.driver_rule_snapshot（历史靠自己解释得通，不靠扩展现算）。

所以拆掉扩展之后历史单照样解释得通 —— 这不是"我们小心一点"，是**结构上就没有依赖**。

## 安全（这个演练会真的动文件，所以规则写死在这里）

1. **开跑前工作区必须是干净的** —— 不干净直接拒绝（否则分不清哪些改动是演练弄的）；
2. 文件移出仓库到一个**临时目录**，跑完按字节还原并逐个核 sha256；
3. try/finally 兜底：中途任何异常都要还原；
4. 还原后再核一次：路由回来了、哈希一致、git status 干净。

用法：python _tools/ops/_r4_remove_drill.py --check   （约 4 分钟：含一次全量静态检查）
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "_tools" / "ops" / "_r4_probe_app.py"
EXT_DIR = ROOT / "backend" / "app" / "extensions" / "unit_conversion"
EXT_TEST = ROOT / "backend" / "tests" / "test_unit_conversion_contract.py"
MANIFEST = EXT_DIR / "manifest.py"
RECORD = ROOT / "_tools" / "ops" / "r4_drill_records" / "remove-drill.json"
ROUTE_MARK = "unit-conversion"
#: 孤儿引用的标记 —— ⚠️ 必须**精确**：第一版拿 "unit_conversion" 当标记，于是核心自己的
#: api/v1/unit_conversions.py（**复数**，那是另一件东西：用户自建换算率的核心实现）、
#: router.py 里那句 import，全被算成了"孤儿引用"（实测踩到）。
#: 子串匹配会把"名字里恰好含这几个字"的东西一起算进来 —— 判据要盯的是**这个扩展**。
ORPHAN_MARKS = ("app.extensions.unit_conversion", "EXT_UNIT_CONVERSION")


def paused_manifest(text: str) -> str:
    """把清单改成"停用"（enabled=False），不碰别的字节。"""
    return text.replace("    why=", "    enabled=False," + chr(10) + "    why=")


class Drill:
    def __init__(self) -> None:
        self.fails: list[str] = []
        self.steps: list[dict[str, str]] = []

    def step(self, name: str, ok: bool, detail: str) -> None:
        self.steps.append({"step": name, "verdict": "OK" if ok else "FAIL", "detail": detail})
        print("  [" + ("OK" if ok else "FAIL") + "] " + name + " —— " + detail)
        if not ok:
            self.fails.append(name + "：" + detail)


def run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str]:
    r = subprocess.run(cmd, cwd=str(cwd or ROOT), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def probe() -> dict:
    """问探针：应用起得来吗、挂了哪些路由、模型里有哪些表。"""
    code, out = run([sys.executable, str(PROBE)])
    for line in reversed(out.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                continue
    return {"boot": False, "boot_error": "探针没有给出 JSON（退出码 " + str(code) + "）",
            "routes": [], "tables": []}


def hashes(paths: list[Path]) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in paths:
        if p.is_file():
            out[str(p.relative_to(ROOT))] = hashlib.sha256(p.read_bytes()).hexdigest()
        elif p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and "__pycache__" not in f.parts:
                    out[str(f.relative_to(ROOT))] = hashlib.sha256(f.read_bytes()).hexdigest()
    return out


def orphan_hits() -> list[str]:
    """生产代码里还有没有引用它的地方（orphan import / config）。

    只扫 backend/：`_tools/` 下的演练脚本与检查器**本来就该提到它**
    （要拆的就是它），把它们算进来等于让判据自己把自己判红。
    """
    hits: list[str] = []
    for base in (ROOT / "backend",):
        for f in sorted(base.rglob("*.py")):
            if "__pycache__" in f.parts or "extensions/unit_conversion" in str(f).replace(chr(92), "/"):
                continue
            if f == Path(__file__).resolve():
                continue          # 演练脚本自己当然会提到它
            text = f.read_text(encoding="utf-8", errors="replace")
            for w in ORPHAN_MARKS:
                if w in text:
                    hits.append(str(f.relative_to(ROOT)).replace(chr(92), "/") + " <- " + w)
    return hits


def main() -> int:
    d = Drill()
    print("== Remove 演练：完整拆掉 unit_conversion，核心照样成立 ==")
    code, out = run(["git", "status", "--porcelain"])
    if code != 0 or out.strip():
        print("工作区不干净，拒绝开跑（否则分不清哪些改动是演练弄的）。先提交或还原。")
        return 1
    if not EXT_DIR.is_dir():
        print("找不到扩展目录 " + str(EXT_DIR))
        return 1

    before_hash = hashes([EXT_DIR, EXT_TEST])
    before = probe()
    before_routes = len(before.get("routes", []))
    before_tables = before.get("tables", [])
    has_route = any(ROUTE_MARK in r for r in before.get("routes", []))
    d.step("前提：工作区干净、应用起得来、扩展在位",
           before.get("boot") and has_route and bool(before_hash),
           "路由 " + str(before_routes) + " 条（含扩展那条）/ 文件 " + str(len(before_hash))
           + " 个 / 表 " + str(len(before_tables)) + " 张")

    tmp = Path(tempfile.mkdtemp(prefix="r4_remove_drill_"))
    moved_ext = tmp / "unit_conversion"
    moved_test = tmp / EXT_TEST.name
    original_manifest = MANIFEST.read_text(encoding="utf-8")
    try:
        # ---- 1. 停用（Disable）：代码还在，只是不装 ----
        # ⚠️ 一律 write_bytes：Path.write_text 在 Windows 上会把 \n 翻成 \r\n，
        #    于是"按字节还原"会静默变成"内容一样、字节不一样"（实测踩到：git diff 是空的，
        #    而 sha256 变了 —— 正是本仓库 AGENTS.md 里那条"别用 PowerShell 往返改文件"的同一类坑）。
        MANIFEST.write_bytes(paused_manifest(original_manifest).encode("utf-8"))
        paused = probe()
        paused_has_route = any(ROUTE_MARK in r for r in paused.get("routes", []))
        d.step("1 停用（Disable）：清单 enabled=False",
               paused.get("boot") and not paused_has_route and EXT_DIR.is_dir(),
               "起得来=" + str(paused.get("boot")) + " 路由消失=" + str(not paused_has_route)
               + " 代码还在=" + str(EXT_DIR.is_dir())
               + ("；起不来的原因：" + str(paused.get("boot_error"))[:160] if not paused.get("boot") else ""))
        MANIFEST.write_bytes(original_manifest.encode("utf-8"))
        back = probe()
        d.step("1b 还原停用：路由回来", any(ROUTE_MARK in r for r in back.get("routes", [])), "路由回来")

        # ---- 2/3. 卸载 + 删代码 ----
        shutil.move(str(EXT_DIR), str(moved_ext))
        shutil.move(str(EXT_TEST), str(moved_test))
        shutil.rmtree(EXT_DIR.parent / "__pycache__", ignore_errors=True)

        after = probe()
        after_routes = after.get("routes", [])
        d.step("2 卸载（Uninstall）：目录移出仓库",
               not EXT_DIR.exists() and after.get("boot") and not any(ROUTE_MARK in r for r in after_routes),
               "目录没了=" + str(not EXT_DIR.exists()) + " 起得来=" + str(after.get("boot"))
               + " 路由没了=" + str(not any(ROUTE_MARK in r for r in after_routes))
               + ("；起不来的原因：" + str(after.get("boot_error"))[:160] if not after.get("boot") else ""))

        hits = orphan_hits()
        d.step("2b 没有 orphan import / config（代码里不再引用它）", not hits,
               "残留引用 " + str(hits[:3]) if hits else "一处都没有")

        d.step("3 删代码：核心路由只少它那一条",
               len(after_routes) == before_routes - 1,
               "路由 " + str(before_routes) + " -> " + str(len(after_routes)))
        d.step("4 数据：核心事实表一张不少（owns_tables 为空 = 没有数据要删）",
               after.get("tables") == before_tables,
               "表 " + str(len(before_tables)) + " -> " + str(len(after.get("tables", [])))
               + "（逐表名比对一致 = " + str(after.get("tables") == before_tables) + "）")

        code, out = run([sys.executable, "_tools/qa/_check_all.py"])
        tail = [ln.strip() for ln in out.splitlines() if "个检查" in ln and "跑完" in ln]
        # ⚠️ 失败时要说清**是哪一条检查**红了 —— 只打一句"没通过"等于没说（第一版就是这样）。
        bad = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("=====")]
        detail = (tail[-1] if tail else out.strip().splitlines()[-1][:140])
        if code != 0 and bad:
            detail += "；红的是：" + "、".join(b.replace("=", "").strip() for b in bad[:3])
        d.step("3b 全量静态检查（含能力执行点 / 依赖方向 / 数据归属）", code == 0, detail)

        code, out = run([sys.executable, "-m", "pytest", "tests/test_socket_io.py",
                         "tests/test_outbox.py", "tests/test_extension_contracts.py",
                         "tests/test_pricing_contract.py", "-q"], cwd=ROOT / "backend")
        tail = [ln.strip() for ln in out.splitlines() if " passed" in ln or " failed" in ln]
        detail = (tail[-1] if tail else "（没有结果行）")
        if code != 0:
            detail += "；退出码 " + str(code) + "：" + " / ".join(
                ln.strip()[:60] for ln in out.splitlines() if "error" in ln.lower())[:180]
        d.step("3c core smoke（发件箱 / 投递原语 / 两个契约，都不碰那个扩展）", code == 0, detail)
    finally:
        if moved_ext.exists() and not EXT_DIR.exists():
            shutil.move(str(moved_ext), str(EXT_DIR))
        if moved_test.exists() and not EXT_TEST.exists():
            shutil.move(str(moved_test), str(EXT_TEST))
        shutil.rmtree(tmp, ignore_errors=True)
        if MANIFEST.exists() and "enabled=False" in MANIFEST.read_text(encoding="utf-8"):
            MANIFEST.write_bytes(original_manifest.encode("utf-8"))

    after_hash = hashes([EXT_DIR, EXT_TEST])
    final = probe()
    d.step("还原：按字节一致", after_hash == before_hash,
           str(len(after_hash)) + " 个文件逐个核 sha256 —— " + ("一致" if after_hash == before_hash else "有差异"))
    d.step("还原：路由回来、工作区干净",
           any(ROUTE_MARK in r for r in final.get("routes", []))
           and not run(["git", "status", "--porcelain"])[1].strip(),
           "路由在、git status 干净")

    print()
    if d.fails:
        print("Remove 演练不成立：" + str(len(d.fails)) + " 条")
        for f in d.fails:
            print("   - " + f)
        return 1
    print("Remove 演练成立：停用 / 卸载 / 删代码 / 数据四步都做了，核心一路上都在，")
    print("   扩展按字节还原、路由回来、工作区干净。")

    RECORD.parent.mkdir(parents=True, exist_ok=True)
    RECORD.write_text(json.dumps({
        "ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "extension": "unit_conversion",
        "steps": d.steps,
    }, ensure_ascii=False, indent=2) + chr(10), encoding="utf-8")
    print("   证据已写 " + str(RECORD.relative_to(ROOT)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())