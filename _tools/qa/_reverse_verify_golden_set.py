# -*- coding: utf-8 -*-
"""反向验证：把 Golden Set 这套判据逐条弄坏，看它**真的会红**。

## 六种破坏

| # | 注入 | 期望 |
| --- | --- | --- |
| ① | 候选实现把「价目一条分类都没挂 = 通用兜底」改掉 | 红：那几条样例当场 mismatch |
| ② | 候选实现把「同一档多条 = 不猜」改成"取第一条" | 红：pricing-kind-ambiguous 当场 mismatch |
| ③ | 候选实现把「这一单没分类时分类这一维不参与筛选」改掉 | 红：boundary-order-no-category 当场 mismatch |
| ④ | 语料里删掉一个桶的全部样例 | 红：语料缺桶 |
| ⑤ | 语料里把某条样例的期望值改错 | 红：语料的期望与核心不一致 |
| ⑥ | 给一个声明「不适用」的桶造一条样例 | 红：声明了不适用却又有样例 |

⭐ ①②③ 是**同一类**：它们改的都是"听起来无所谓"的边界口径 ——
而这类改动**不会报错、不会崩**，只会让某几张单的运费换个数。这正是 Golden Set 存在的理由。

用法：python _tools/qa/_reverse_verify_golden_set.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import lock_reverse_verify, unlock_reverse_verify  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_golden_set.py"
CORPUS = HERE / "_golden" / "freight_pricing.json"
IMPL = ROOT / "backend/app/extensions/pricing/freight_template.py"

#: 候选实现里的三个边界口径（原文必须一字不差地还在 —— 这也是判据的一部分）
FALLBACK_SRC = "return 1 if not cats else 2"
AMBIG_SRC = "        if len(same) > 1:"
NO_CAT_SRC = "                return 1"


class Sandbox:
    """按字节备份/还原（⛔ 不用 git checkout --：那会抹掉未提交的真实改动）。"""

    def __init__(self) -> None:
        self.saved: dict[Path, bytes] = {}

    def replace(self, p: Path, old: str, new: str) -> None:
        self.saved.setdefault(p, p.read_bytes())
        text = p.read_text(encoding="utf-8")
        assert text.count(old) == 1, p.name + "：锚点出现 " + str(text.count(old)) + " 次（要恰好一次）"
        p.write_bytes(text.replace(old, new).encode("utf-8"))

    def write(self, p: Path, text: str) -> None:
        self.saved.setdefault(p, p.read_bytes())
        p.write_bytes(text.encode("utf-8"))

    def restore(self) -> None:
        for p, raw in self.saved.items():
            p.write_bytes(raw)
        self.saved.clear()


def run_check() -> tuple[int, str]:
    r = subprocess.run([sys.executable, str(CHECK)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=str(ROOT))
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def _drop_bucket(sb: Sandbox, bucket: str) -> None:
    data = json.loads(CORPUS.read_text(encoding="utf-8"))
    data["cases"] = [c for c in data["cases"] if c["bucket"] != bucket]
    assert len(data["cases"]) < 15, "前提不成立：语料里没有 bucket=" + bucket + " 的样例"
    sb.write(CORPUS, json.dumps(data, ensure_ascii=False, indent=2) + chr(10))


def _patch_expect(sb: Sandbox) -> None:
    data = json.loads(CORPUS.read_text(encoding="utf-8"))
    hit = [c for c in data["cases"] if c["id"] == "normal-route-hit"][0]
    hit["expect"]["fee"] = "999.99"
    sb.write(CORPUS, json.dumps(data, ensure_ascii=False, indent=2) + chr(10))


def _add_na_case(sb: Sandbox) -> None:
    data = json.loads(CORPUS.read_text(encoding="utf-8"))
    clone = json.loads(json.dumps([c for c in data["cases"] if c["id"] == "zero-fee"][0]))
    clone["id"] = "unit-bogus"
    clone["bucket"] = "unit"          # ⛔ unit 在 NOT_APPLICABLE 里声明"不适用"
    data["cases"].append(clone)
    sb.write(CORPUS, json.dumps(data, ensure_ascii=False, indent=2) + chr(10))


CASES = [
    ("① 价目没挂分类时不再当通用兜底", lambda sb: sb.replace(
        IMPL, FALLBACK_SRC, "return 2"), "mismatch"),
    ("② 同一档多条时改成「取第一条」（不猜 → 猜）", lambda sb: sb.replace(
        IMPL, AMBIG_SRC, "        if False:"), "mismatch"),
    ("③ 这一单没分类时也让分类参与筛选", lambda sb: sb.replace(
        IMPL, NO_CAT_SRC, "                return 2"), "mismatch"),
    ("④ 语料里删掉 normal 桶的全部样例", lambda sb: _drop_bucket(sb, "normal"), "缺桶"),
    ("⑤ 语料把某条样例的期望金额改错", _patch_expect, "期望与核心不一致"),
    ("⑥ 给声明「不适用」的 unit 桶造一条样例", _add_na_case, "不适用"),
]


def main() -> int:
    bad = 0
    sb = Sandbox()
    lock_reverse_verify()
    try:
        code, out = run_check()
        if code != 0:
            print("❌ 前提不成立：源码完好时 Golden Set 没过")
            print(out[-1500:])
            return 1
        last = [ln for ln in out.splitlines() if ln.strip()][-1]
        print("✅ 前提：源码完好时判据是绿的 —— " + last.strip())
        for label, setup, want in CASES:
            sb.restore()
            setup(sb)
            try:
                code, out = run_check()
            finally:
                sb.restore()
            hit = code != 0 and want in out
            detail = ("报红并命中「" + want + "」") if hit else (
                "判据居然还是绿的" if code == 0 else "退出了，但没报出「" + want + "」")
            print("  [" + ("OK" if hit else "MISS") + "] " + label + " → " + detail)
            if not hit:
                bad += 1
                for ln in [x.strip() for x in out.splitlines() if "FAIL" in x or "❌" in x][:4]:
                    print("       判据实际报的：" + ln[:140])
        sb.restore()
        code, out = run_check()
        ok = code == 0
        print("  [OK] 还原后判据全绿" if ok else "  [MISS] 还原后判据没恢复")
        bad += 0 if ok else 1
    finally:
        sb.restore()
        unlock_reverse_verify()
    total = len(CASES) + 1
    print()
    if bad:
        print("❌ " + str(bad) + "/" + str(total) + " 条不成立")
        return 1
    print("✅ " + str(total) + "/" + str(total) + " 全部成立：边界口径被改坏 / 语料缺桶 / 期望改错 / "
          "声明的「不适用」被打脸 —— 都会被当场点出来")
    return 0


if __name__ == "__main__":
    sys.exit(main())
