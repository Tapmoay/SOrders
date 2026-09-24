#!/usr/bin/env python3
"""反向验证 _tools/ops/_check_ops.py（运维监控自己的判据）真的抓得住那几条。

## 为什么监控的判据特别需要反向验证
健康检查平时**什么都不说**（全绿是静默的），所以它坏掉也没人会注意到 —— 而它恰好是
报告 §15 点名的那件事（「出现过证书过期两个月无人发现」）唯一的外部信号。
这条红线此前**一条反向验证都没有**（2026-09-25 补）。

## 六种破坏（每一种都必须让红线当场红，且报出**对应**那条判据）
| # | 注入 | 现实里谁会这么干 |
| --- | --- | --- |
| ① | 事实脚本里混进一句 delete | 排障时顺手加一句「清一下」，忘了它是个只读监控 |
| ② | 另一个脚本里又写了一遍生产 IP | 复制粘贴时图省事 |
| ③ | 退出码不再分档（fail 与 warn 都 return 1） | 「反正都是非零」→ cron/CI 拿到的信号失去意义 |
| ④ | 例外命中时降级成 ok（不是 warn） | 「既然已知，那就当正常吧」→ 例外表变成垃圾桶 |
| ⑤ | 例外条目的理由被改成一句话 | 后来的人懒得写 → 没人知道它为什么被豁免 |
| ⑥ | 化石探测被删掉 | 证书处理完了、例外条目还留着，谁也不会发现 |

⚠️ 与仓库里其它反向验证同一套纪律：按**字节**备份/还原、跑完逐文件核对、不碰 git checkout --。

用法：python _tools/qa/_reverse_verify_ops.py
      python _tools/qa/_reverse_verify_ops.py --list
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
CHECK = ROOT / "_tools/ops/_check_ops.py"
PROD = "_tools/ops/_prodssh.py"
HEALTH = "_tools/ops/_health_check.py"

CASES: list[tuple[str, str, str, str, str]] = [
    (
        "① 事实脚本里混进一句 delete（只读监控开始改生产库）",
        PROD,
        '_FACTS_TEMPLATE = r"""set +e',
        '_FACTS_TEMPLATE = r"""set +e\ndelete from orders where id = 0;',
        "事实脚本里出现了写操作",
    ),
    (
        "② 另一个脚本里又写了一遍生产 IP（复制粘贴图省事）",
        HEALTH,
        "import _prodssh  # noqa: E402",
        'import _prodssh  # noqa: E402\nPROD_IP_COPIED = "8.145.40.22"',
        "又写了一遍生产主机",
    ),
    (
        "③ 退出码不再分档（fail 与 warn 都 return 1）",
        HEALTH,
        "    return 2 if fails else (1 if warns else 0)",
        "    return 1 if fails else 0",
        "退出码不再分档",
    ),
    (
        "④ 例外命中时降级成 ok（例外表变成垃圾桶）",
        HEALTH,
        '            rows.append(("warn", f"证书 {name}（已知/已接受）",',
        '            rows.append(("ok", f"证书 {name}（已知/已接受）",',
        "例外命中时没有降级成 warn",
    ),
    (
        "⑤ 例外条目的理由被改成一句话（后来的人懒得写）",
        HEALTH,
        '                        "**备案完成、或改用 DNS-01 挑战之后，删掉这一条。**",',
        '                        "先不管。",',
        "理由太短",
    ),
    (
        "⑥ 化石探测被删掉（证书处理完了例外条目还留着）",
        HEALTH,
        "    stale_accepted = sorted(set(ACCEPTED_CERT) - accepted_hit)",
        "    stale_accepted: list[str] = []",
        "没有化石探测",
    ),
    (
        "⑦ 例外表被写坏（语法错）→ 四条约束必须一起报出来，而不是静默空转",
        HEALTH,
        "ACCEPTED_CERT: dict[str, str] = {",
        "ACCEPTED_CERT: dict[str, str] = {!!}",
        "解析不出 ACCEPTED_CERT",
    ),
]

CRLF = chr(13) + chr(10)


class Sandbox:
    """按**字节**记账的注入沙箱：每次注入前先还原上一轮，跑完再逐字节核对。"""

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
    proc = subprocess.run([sys.executable, str(CHECK), "--check"], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=str(ROOT))
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        for i, (name, rel, _o, _n, want) in enumerate(CASES, 1):
            print(str(i) + ". " + name + "\n      " + rel + "   ← 期望被「" + want + "」抓到")
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
            hit = code != 0 and ("BAD " in out) and (want in out)
            if hit:
                print("  [OK] " + label + " → 红线报红并命中「" + want + "」")
            else:
                bad += 1
                why = "红线居然还是绿的" if code == 0 else "退出了，但没报出「" + want + "」"
                print("  [MISS] " + label + " → " + why)
                for ln in [x.strip() for x in out.splitlines() if x.strip().startswith("BAD")][:5]:
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
    print(f"✅ {total}/{total} 全部成立：运维监控的每一类静默失效都会被对应的判据抓到")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
