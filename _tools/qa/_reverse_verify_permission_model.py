#!/usr/bin/env python3
"""反向验证 `_tools/qa/_check_permission_model.py` 真的抓得住那几类错误。

## 为什么
这一条判据守的是**报告 §9 那三维模型与例外声明**。它最容易的退化方式不是"报错"，
而是**悄悄变成装饰**：Scope 表被掏空、理由被写成两个字、例外又回到函数体里硬编码 ——
三种都不会让任何业务用例失败，只会让「收敛成统一模型」这句话变成一句口号。

## 六种破坏
| # | 注入 | 期望 |
| --- | --- | --- |
| ① | 删掉一个权限点的 Scope 声明 | 红：没有 Scope 声明 |
| ② | Scope 取值改成表外的值 | 红：不在 SCOPE_KINDS 里 |
| ③ | Scope 的理由缩成两个字 | 红：理由太短 |
| ④ | 例外回到函数体里硬编码角色名 | 红：不许硬编码角色名比较 |
| ⑤ | 例外理由删掉「什么时候删掉这一条」 | 红：没写什么时候删 |
| ⑥ | 权限点值不再带冒号（资源/动作分不清） | 红：不是 resource:action 的形状 |

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
CHECK = ROOT / "_tools/qa/_check_permission_model.py"
RBAC = "backend/app/core/rbac.py"
STATS_LINE = '    Permission.STATS_READ: ("all", "报表是全店口径（营业额/毛利/司机绩效），没有「只看自己那份」的版本"),'

CASES: list[tuple[str, str, str, str, str]] = [
    (
        "① 删掉一个权限点的 Scope 声明（模型缺一维）",
        RBAC,
        STATS_LINE + '\n',
        '',
        "没有 Scope 声明",
    ),
    (
        "② Scope 取值改成表外的值（没人能解释它怎么对应行级过滤）",
        RBAC,
        'Permission.STATS_READ: ("all", ', 
        'Permission.STATS_READ: ("everything", ', 
        "不在 SCOPE_KINDS",
    ),
    (
        "③ Scope 的理由缩成两个字（等于没写）",
        RBAC,
        '"报表是全店口径（营业额/毛利/司机绩效），没有「只看自己那份」的版本"',
        '"全局"',
        "理由太短",
    ),
    (
        "④ 例外**又**在函数体里硬编码角色名（表还在 —— 测的是第二条判据）",
        RBAC,
        '    if key in BYPASS_ROLES:\n        return True',
        '    if key == UserRole.DISPATCHER.value:\n        return True\n'
        '    if key in BYPASS_ROLES:\n        return True',
        "硬编码",
    ),
    (
        "⑦ 函数体干脆不走 BYPASS_ROLES 了（例外表变成摆设）",
        RBAC,
        '    if key in BYPASS_ROLES:',
        '    if False:',
        "没有走 BYPASS_ROLES",
    ),
    (
        "⑤ 例外理由删掉「什么时候删掉这一条」",
        RBAC,
        '"删掉这一条，改成逐格授权。**"',
        '"以后再说。**"',
        "什么时候删掉这一条",
    ),
    (
        "⑥ 权限点值不再带冒号（资源/动作分不清）",
        RBAC,
        '    ORDER_CREATE = "order:create"',
        '    ORDER_CREATE = "ordercreate"',
        "resource:action",
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
            print(f"{i}. {name}\n      {rel}   ← 期望被「{want}」抓到")
        return 0

    bad = 0
    sb = Sandbox()
    lock_reverse_verify()
    try:
        code, out = run_check()
        if code != 0:
            print("❌ 前提不成立：源码完好时这条红线就没过")
            print(out[-1500:])
            return 1
        last = [ln for ln in out.splitlines() if ln.strip()][-1]
        print("✅ 前提：源码完好时红线是绿的 —— " + last.strip())
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
            hit = code != 0 and want in out
            if hit:
                print("  [OK] " + label + " → 红线报红并命中「" + want + "」")
            else:
                bad += 1
                why = "红线居然还是绿的" if code == 0 else "退出了，但没报出「" + want + "」"
                print("  [MISS] " + label + " → " + why)
                for ln in [x.strip() for x in out.splitlines() if x.strip().startswith("❌")][:5]:
                    print("       红线实际报的：" + ln)
        sb.restore()
        code, out = run_check()
        ok = code == 0
        print("  [OK] 还原后红线全绿" if ok else "  [MISS] 还原后红线没恢复")
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
    print(f"✅ {total}/{total} 全部成立：模型缺维 / 取值越界 / 理由敷衍 / 例外回流 / 形状坏掉都会被抓到")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())