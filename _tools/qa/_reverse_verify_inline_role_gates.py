#!/usr/bin/env python3
"""反向验证 `_tools/qa/_check_inline_role_gates.py` 真的抓得住"体内角色门槛长回来"。

## 为什么
这条判据守的是报告 §9 的**授权统一模型**。它的退化方式不是"报错"，而是**悄悄失效**：
棘轮上限被自己调大、清单变成化石、扫描器扫不到东西却仍然绿、
或者矫枉过正把"不 raise 的角色分支"也算成门槛（那会让判据变成噪音、最后被人关掉）。

## 九个用例
| # | 注入 | 期望 |
| --- | --- | --- |
| ① | 已收敛文件里加回一段体内角色门槛 | 红：声明已收敛 |
| ② | 别的文件里新增一处体内角色门槛 | 红：涨到 45 处（超棘轮） |
| ③ | 台账追加一条**增大**且没写理由的记录 | 红：没写「理由:」 |
| ④ | 台账追加一条增大**并写明理由**的记录 | **绿**（如实承认这是被允许的松绑路径） |
| ⑤ | 清单里的路径改成不存在的文件 | 红：清单化石 |
| ⑥ | API 目录指到不存在的地方（扫描空转） | 红：只扫到 0 个 |
| ⑦ | 台账说明缩成两个字 | 红：说明太短 |
| ⑧ | 加一段**不 raise** 的角色分支（数据范围裁剪） | **绿**（不许误报） |
| ⑨ | 加一个**不由角色决定**的 403 | **绿**（不许误报） |

⚠️ 这条判据**挡不住什么**（如实写明，不假装它无懈可击）：
有意**同时**改台账与代码的人能绕过去 —— 台账是自证的，"把上限调大"这件事
在代码里没有独立事实可对质。它挡的是真实发生的那一类："顺手又写了一处体内门槛、
谁也没注意到"；以及"改完又长回来"。同时改两处的动作会出现在 diff 里，
由人看出来（这也正是台账要写日期与说明的原因）。

⚠️ 与仓库里其它 `_reverse_verify_*.py` 同一套纪律：按**字节**备份/还原、跑完逐文件核对、
⛔ 全程不碰 `git checkout --`。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import lock_reverse_verify, unlock_reverse_verify  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_inline_role_gates.py"
GATE_CHECK = "_tools/qa/_check_inline_role_gates.py"
EXPENSE = "backend/app/api/v1/expense_categories.py"
PRODUCTS = "backend/app/api/v1/products.py"
CASH = "backend/app/api/v1/cash_flows.py"
QUERY = "backend/app/api/v1/orders_query.py"

GATE = (
    chr(10) + "    if user_role_key(current) != UserRole.DISPATCHER.value:" + chr(10)
    + "        raise HTTPException(status_code=403, detail=" + chr(34) + "无权" + chr(34) + ")"
)
def _ledger_tail() -> str:
    """从判据源码里**现取**计数台账的尾部（最后一条 + 收尾的 `]`）。

    ⛔ 2026-09-26 修：原来写死的是「2026-09-25 首次建账」那一条 —— 台账后来又追加了 4 条，
    写死的锚点出现 0 次 ⇒ ③④ 两条注入**恒 SKIP**（而 SKIP 在本仓库计为不成立）。
    台账本来就是**会长的东西**，锚点必须现取（与 `_reverse_verify_reverse_verify_restore.py`
    里 `_live_anchor` 同一个教训）。
    """
    import io as _io

    src = _io.open(CHECK, encoding="utf-8").read()
    head = 'HISTORY: list[tuple[str, int, str]] = ['
    i = src.index(head)
    j = src.index(chr(10) + ']', i)
    body = src[i:j + 2].splitlines()
    k = len(body) - 2
    while k > 0 and not body[k].startswith('    ("'):
        k -= 1
    return chr(10).join(body[k:])


LEDGER_TAIL = _ledger_tail()


def _ledger_first_reason() -> str:
    """台账**第一条**的「说明」——也从判据源码里现取，不手抄。

    ⚠️ 为什么不用最后一条：台账里**后面的条目可能是好几个字符串拼起来的**（跨行续写），
    只取其中一段去缩短，整条说明照样超过字数下限 ⇒ ⑦ 号注入会「判据居然还是绿的」（实测踩到）。
    第一条是**单串**，缩短它才能真的把它压到下限以下。
    """
    import io as _io
    import re as _re

    src = _io.open(CHECK, encoding="utf-8").read()
    m = _re.search(r"\(\s*\"[^\"]*\",\s*\d+,\s*\"([^\"]+)\"", src)
    return m.group(1) if m else ""


LEDGER_REASON = _ledger_first_reason()

CASES: list[tuple[str, str, str, str, str | None]] = [
    (
        "① 已收敛文件里加回一段体内角色门槛（改完又长回来）",
        EXPENSE,
        '"""开销分类名册（按显示顺序）。**仅派单员**（开销这一块本来就只有他能看）。"""',
        '"""开销分类名册（按显示顺序）。**仅派单员**（开销这一块本来就只有他能看）。"""' + GATE,
        "声明已收敛",
    ),
    (
        "② 别的文件里新增一处体内角色门槛（顺手又抄了一遍）",
        PRODUCTS,
        "    if include_inactive and rk not in (UserRole.DISPATCHER.value, UserRole.SHIPPER.value):",
        GATE + chr(10) + "    if include_inactive and rk not in (UserRole.DISPATCHER.value, UserRole.SHIPPER.value):",
        # ⛔ 2026-09-26 修期望词：注入之后判据**确实报红**（退出码 1），但报的是「app/api/v1/products.py
        #    声明已收敛…但体内还有 1 处：list_products:98」—— 比当年那句「涨到 45 处」**更具体**
        #    （先撞上的是「已收敛文件里不许再长」那条）。判据没病，是期望词过期了。
        "声明已收敛",
    ),
    (
        "③ 台账追加一条**增大**且没写理由的记录（悄悄松掉棘轮）",
        GATE_CHECK,
        LEDGER_TAIL,
        LEDGER_TAIL[:-1] + chr(10) + '    ("2026-09-26", 45, "涨了一点点"),' + chr(10) + "]",
        "理由:",
    ),
    (
        "④ 台账追加一条增大**并写明理由**的记录（如实记录 → 允许）",
        GATE_CHECK,
        LEDGER_TAIL,
        LEDGER_TAIL[:-1] + chr(10)
        + '    ("2026-09-26", 45, "理由:新增的这一处依赖请求内容，签名级暂时表达不了，等有读参数的 Depends 再降回来"),'
        + chr(10) + "]",
        None,
    ),
    (
        "⑤ 清单里的路径改成不存在的文件（清单化石）",
        GATE_CHECK,
        '"app/api/v1/expense_categories.py":',
        '"app/api/v1/no_such_file.py":',
        "清单化石",
    ),
    (
        "⑥ API 目录指到不存在的地方（扫描空转却仍然绿）",
        GATE_CHECK,
        'API_DIR = ROOT / "backend/app/api"',
        'API_DIR = ROOT / "backend/app/api_gone"',
        "只扫到 0 个",
    ),
    (
        "⑦ 台账说明缩成两个字（等于没写）",
        GATE_CHECK,
        '"' + LEDGER_REASON + '"',
        '"建账"',
        "个字（下限",
    ),
    (
        "⑧ 加一段**不 raise** 的角色分支（数据范围裁剪，不是门槛）",
        CASH,
        "    stmt = (",
        "    if user_role_key(current) == UserRole.DRIVER.value:" + chr(10)
        + "        limit = min(limit, 50)" + chr(10) + "    stmt = (",
        None,
    ),
    (
        "⑨ 加一个**不由角色决定**的 403（这张单不是你的）",
        QUERY,
        'detail="无权查看隔离数据")',
        'detail="无权查看隔离数据")' + chr(10) + "    if limit is not None and limit < 0:" + chr(10)
        + '        raise HTTPException(status_code=403, detail="参数不对")',
        None,
    ),
]

CRLF = chr(13) + chr(10)


class Sandbox:
    """按**字节**记账的注入沙箱。"""

    def __init__(self) -> None:
        self.saved: dict[Path, bytes] = {}

    def apply(self, rel: str, old: str, new: str) -> None:
        p = ROOT / rel
        if not p.exists():
            raise ValueError("找不到 " + rel)
        self.saved.setdefault(p, p.read_bytes())
        raw = p.read_bytes()
        crlf = CRLF.encode("utf-8") in raw
        text = raw.decode("utf-8")
        if old not in text:
            # 第二轮 R2-05：报表源码搬进了 `services/reports/` —— **锚点跟着搬家走**。
            # 判据读的是「并集」（`_airepo.reports_source`），注入器也必须打在那份含原文的文件上，
            # 否则沙箱找不到原文 → [SKIP] → 而 SKIP 在本仓库是**计为不成立**的。
            # ⛔ 不逐条改锚点、也不改目标路径：以后报表再搬一次，这里自动跟上。
            import sys as _sys
            from pathlib import Path as _P
            _sys.path.insert(0, str(_P(__file__).resolve().parent.parent / "ai"))
            from _airepo import reports_files as _rf
            for _c in _rf():
                _t = _c.read_text(encoding="utf-8", errors="replace")
                if _t.count(old) == 1:
                    p = _c
                    raw = p.read_bytes()
                    text = raw.decode("utf-8")
                    if CRLF.encode("utf-8") in raw:
                        text = text.replace(CRLF, chr(10))
                    self.saved.setdefault(p, raw)
                    break
        if crlf:
            text = text.replace(CRLF, chr(10))
        if text.count(old) != 1:
            raise ValueError(rel + " 里锚点出现 " + str(text.count(old)) + " 次（要恰好一次）")
        text = text.replace(old, new, 1)
        p.write_bytes((text.replace(chr(10), CRLF) if crlf else text).encode("utf-8"))

    def restore(self) -> None:
        for p, raw in self.saved.items():
            p.write_bytes(raw)

    def dirty(self) -> list[str]:
        return [str(p.relative_to(ROOT)) for p, raw in self.saved.items() if p.read_bytes() != raw]


def run_check() -> tuple[int, str]:
    proc = subprocess.run([sys.executable, str(CHECK)], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=str(ROOT))
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        for i, (name, rel, _o, _n, want) in enumerate(CASES, 1):
            goal = "被「" + want + "」抓到" if want else "**必须仍然绿**"
            print(str(i) + ". " + name + chr(10) + "      " + rel + "   ← " + goal)
        return 0

    bad = 0
    sb = Sandbox()
    lock_reverse_verify()
    try:
        code, out = run_check()
        if code != 0:
            print("❌ 前提不成立：源码完好时这条判据就没过")
            print(out[-1500:])
            return 1
        last = [ln for ln in out.splitlines() if ln.strip()][-1]
        print("✅ 前提：源码完好时判据是绿的 —— " + last.strip())
        for label, rel, old, new, want in CASES:
            sb.restore()
            try:
                sb.apply(rel, old, new)
                code, out = run_check()
            except ValueError as exc:
                print("  [SKIP] " + label + " —— " + str(exc))
                bad += 1
                continue
            finally:
                sb.restore()
            if want is None:
                if code == 0:
                    print("  [OK] " + label + " → 判据仍然绿（没有误报）")
                else:
                    bad += 1
                    print("  [MISS] " + label + " → 误报了！这不是门槛，不该红：")
                    for ln in [x.strip() for x in out.splitlines() if x.strip().startswith("❌")][:3]:
                        print("       判据实际报的：" + ln)
                continue
            hit = code != 0 and want in out
            if hit:
                print("  [OK] " + label + " → 判据报红并命中「" + want + "」")
            else:
                bad += 1
                why = "判据居然还是绿的" if code == 0 else "退出了，但没报出「" + want + "」"
                print("  [MISS] " + label + " → " + why)
                for ln in [x.strip() for x in out.splitlines() if x.strip().startswith("❌")][:5]:
                    print("       判据实际报的：" + ln)
        sb.restore()
        code, out = run_check()
        ok = code == 0
        print("  [OK] 还原后判据全绿" if ok else "  [MISS] 还原后判据没恢复")
        bad += 0 if ok else 1
    finally:
        sb.restore()
        unlock_reverse_verify()

    dirty = sb.dirty()
    if dirty:
        bad += 1
        print("⛔ 跑完没逐字节还原：" + "、".join(dirty))
    total = len(CASES) + 1
    print()
    if bad:
        print(f"❌ {bad}/{total} 条不成立")
        return 1
    print(f"✅ {total}/{total} 全部成立：回退 / 新增 / 松棘轮 / 清单化石 / 扫描空转 / 说明敷衍都会被抓到，"
          "而数据裁剪与非角色 403 不会被误报")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
