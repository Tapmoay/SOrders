"""反向验证 BUG-0009（看不见的字不再能写进来）那道闸**真的在拦**。

2026-10-03 用户点名：查清地点卡上那几个「??????」是怎么写进去的（提示「可能是关于 AI 的功能」）。
查下来：库里存的就是问号本身、原文不可还原，写入端已经分不出是人工还是 AI —— 所以修法是
「在自由文本入参上设一道闸：不可显示字符 + 整串问号一律拒收，只拒收不替换，历史那行不动」。
这份脚本逐条把闸撤回（或反向收紧），证明对应的检查（判据脚本 / 回归用例）会红。

| 注入 | 应该红的检查 |
|---|---|
| 整串问号那条失效 | 只有问号被拒 那条用例 |
| 不判不可显示字符 | 看不见的字符被拒 那条用例 |
| 反向收紧成「含连续问号就拒」 | 夹问号的正常文字放行 那条用例（会误伤真实表达） |
| 把制表符也算坏字符 | 常见空白放行 那条用例 |
| 混入不按子类名单走（type(self) 变空） | 判据 |
| 校验器整个失效（挂了名单但不过闸） | 地点建单被拦 那条用例 |
| 订单名单漏掉「货主姓名」/ 地点模型摘掉混入 | 判据 |
| 共享地点库绕过闸（identify_error 不再 find） | 判据 |
| FIELD_CN 摘掉字段中文名（提示里冒英文 key） | 判据 |
| 名单里打错一个字（getattr 静默跳过） | 判据 |
| 回归用例掉数 / 登记表换 ID / 文档缺节或写不清根因 | 判据 |
| 地址与地点模型的 GeoInput 接线全丢（BUG-0009 让基类列表多了一层，红线那条正则跟着放宽过） | `_tools/ai/_check_ai_guardrails.py` §27 红线 |

⚠️ 快照/还原按**字节**做（仓库里有 CRLF 文件），跑完逐字节核对。

用法：python _tools/qa/_reverse_verify_unshowable_text_guard.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
JUDGE = ROOT / "_tools/qa/_check_unshowable_text_guard.py"
# 另一族红线（AI 护栏 §27 输入边界）——那里有一条「地址/订单的 lat/lng 都接上了」，
# BUG-0009 给这几个模型多继承了一层 ShowableModel，那条正则跟着放宽；这里钉住「放宽之后仍然会红」。
GUARD_AI = ROOT / "_tools/ai/_check_ai_guardrails.py"

GUARD = "backend/app/core/text_guard.py"
TEXT = "backend/app/schemas/text.py"
ORDER = "backend/app/schemas/order.py"
SHIPPER = "backend/app/schemas/shipper.py"
PLACE = "backend/app/services/place_service.py"
VERR = "backend/app/core/validation_errors.py"
KTEST = "backend/tests/test_text_guard.py"
DOC = "docs/changes/BUG-0009.md"
REG = "docs/changes/README.md"

ONLY = KTEST + "::test_only_marks_is_rejected"
BACK = KTEST + "::test_invisible_chars_are_rejected"
INSIDE = KTEST + "::test_marks_inside_real_text_pass"
WS = KTEST + "::test_normal_whitespace_passes"
LOC_CREATE = KTEST + "::test_create_location_with_only_marks_is_rejected"

#: (说明, 相对路径, 注入, 期望变红的 node；`CHECK:` 前缀 = 跑判据脚本并找那条 [FAIL])
CASES: list[tuple[str, str, object, str]] = [
    (
        "整串问号那条失效（?????? 又能一路存进库）",
        GUARD,
        lambda s: s.replace("    if stripped and all(ch in _QUESTION_MARKS or ch.isspace() for ch in stripped):", "    if False:", 1),
        ONLY,
    ),
    (
        "不判不可显示字符（U+FFFD / 控制字又混得进来）",
        GUARD,
        lambda s: s.replace("    if _BAD_CHARS.search(text):", "    if False and _BAD_CHARS.search(text):", 1),
        BACK,
    ),
    (
        "反向收紧成「含连续问号就拒」（门牌??? 这种真实表达被误伤）",
        GUARD,
        lambda s: s.replace(
            "    if stripped and all(ch in _QUESTION_MARKS or ch.isspace() for ch in stripped):",
            '    if "??" in stripped or "？？" in stripped:',
            1,
        ),
        INSIDE,
    ),
    (
        "把制表符也算成不可显示字符（正常的多行文本被拒）",
        GUARD,
        lambda s: s.replace("[\\u0000-\\u0008", "[\\u0000-\\u0008\\u0009", 1),
        WS,
    ),
    (
        "混入不再按子类名单走（type(self) 变成空名单 = 谁也不过闸）",
        TEXT,
        lambda s: s.replace("text_guard.ensure_fields(self, type(self).SHOWABLE_FIELDS)", "text_guard.ensure_fields(self, ())", 1),
        "CHECK:type(self)",
    ),
    (
        "校验器整个失效（名单挂着但没人查）",
        TEXT,
        lambda s: s.replace("        text_guard.ensure_fields(self, type(self).SHOWABLE_FIELDS)\n", "        pass\n", 1),
        LOC_CREATE,
    ),
    (
        "订单名单漏掉「收货人姓名」（那一单坏掉的三个字段之一）",
        ORDER,
        lambda s: s.replace('        "contact_dongjia_name",\n', "", 1),
        "CHECK:收货人姓名",
    ),
    (
        "地点模型摘掉混入（出脏数据的那张表不再过闸）",
        SHIPPER,
        lambda s: s.replace("class LocationCreate(ShowableModel, GeoInput):", "class LocationCreate(GeoInput):", 1),
        "CHECK:地点",
    ),
    (
        "共享地点库绕过闸（identify_error 不再调 find）",
        PLACE,
        lambda s: s.replace("        err = text_guard.find(value, field)", "        err = None", 1),
        "CHECK:identify_error",
    ),
    (
        "FIELD_CN 摘掉字段中文名（提示里冒英文 key）",
        VERR,
        lambda s: s.replace('    "contact_dongjia_name": "收货人姓名",\n', "", 1),
        "CHECK:FIELD_CN",
    ),
    (
        "名单里打错一个字（getattr 静默跳过 = 那个字段永远不过闸）",
        SHIPPER,
        lambda s: s.replace('"receiver_name", "detail_address"', '"receiver_nam", "detail_address"', 1),
        "CHECK:真字段",
    ),
    (
        "回归用例掉到 12 条以下（少一条就没人钉了）",
        KTEST,
        lambda s: s.replace("def test_normal_whitespace_passes(", "def _test_normal_whitespace_passes(", 1),
        "CHECK:回归用例",
    ),
    (
        "登记表里换成别的 ID",
        REG,
        lambda s: s.replace("| `BUG-0009` |", "| `BUG-XXXX` |", 1),
        "CHECK:改动登记表",
    ),
    (
        "改动文档里不提「拦在入口」（根因与修法写不清）",
        DOC,
        lambda s: s.replace("拦在入口", "入口处理"),
        "CHECK:文档写清了根因与修法",
    ),
    (
        "改动文档里不提历史脏行（清数据那条不写「要用户确认」）",
        DOC,
        lambda s: s.replace("id=94", "id=95"),
        "CHECK:文档写明历史脏数据",
    ),
    (
        "改动文档缺一节（九节少一个）",
        DOC,
        lambda s: s.replace("## ⑨ 关闭（六格）", "## 关闭（六格）", 1),
        "CHECK:改动文档九节齐全",
    ),
    (
        "地址与地点模型的 GeoInput 接线全丢（这一层混入改了基类列表，红线那条正则放宽后必须还认得出）",
        SHIPPER,
        lambda s: s.replace("(ShowableModel, GeoInput):", "(ShowableModel):"),
        "GUARD:地址/订单的 lat/lng 都接上了",
    ),
]


def read_src(p: Path) -> tuple[str, bool]:
    data = p.read_bytes()
    return data.decode("utf-8").replace("\r\n", "\n"), b"\r\n" in data


def write_src(p: Path, text: str, crlf: bool) -> None:
    data = text.replace("\r\n", "\n")
    if crlf:
        data = data.replace("\n", "\r\n")
    p.write_bytes(data.encode("utf-8"))


def run_test(node: str) -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, "-m", "pytest", node, "-q", "--no-header"],
        cwd=str(ROOT / "backend"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def run_judge() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(JUDGE)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def run_guardai() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(GUARD_AI)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    fails: list[str] = []
    code, out = run_judge()
    if code != 0:
        print("❌ 前提不成立：源码完好时判据脚本就没过")
        print(out[-1500:])
        return 1
    code, out = run_test("tests/test_text_guard.py")
    if code != 0:
        print("❌ 前提不成立：源码完好时回归用例就没过")
        print(out[-1500:])
        return 1
    print("✅ 前提：源码完好时判据脚本与 13 条回归用例都是绿的")

    touched = sorted({rel for _l, rel, _m, _n in CASES})
    originals = {rel: (ROOT / rel).read_bytes() for rel in touched}
    crlfs = {rel: b"\r\n" in originals[rel] for rel in touched}

    for label, rel, mutate, node in CASES:
        path = ROOT / rel
        plain = originals[rel].decode("utf-8").replace("\r\n", "\n")
        mutated = mutate(plain)
        if mutated == plain:
            fails.append(f"{label}：注入没生效（锚点变了，请更新本脚本）")
            print(f"  [SKIP] {label}")
            continue
        try:
            write_src(path, mutated, crlfs[rel])
            if node.startswith("CHECK:"):
                jcode, jout = run_judge()
                expect = node.split(":", 1)[1]
                hit = jcode != 0 and any("[FAIL]" in ln and expect in ln for ln in jout.splitlines())
            elif node.startswith("GUARD:"):
                gcode, gout = run_guardai()
                expect = node.split(":", 1)[1]
                hit = gcode != 0 and any("[FAIL]" in ln and expect in ln for ln in gout.splitlines())
            else:
                tcode, _tout = run_test(node)
                hit = tcode != 0
        finally:
            path.write_bytes(originals[rel])
        kind = "判据" if node.startswith("CHECK:") else ("红线" if node.startswith("GUARD:") else "回归测试")
        if hit:
            print(f"  [OK] {label} → {kind}报红")
        else:
            fails.append(f"{label}：注入之后**没有任何检查报红**（闸没有被钉住）")
            print(f"  [MISS] {label} → 全绿")

    dirty = [rel for rel in touched if (ROOT / rel).read_bytes() != originals[rel]]
    if dirty:
        fails.append("跑完没逐字节还原：" + "、".join(dirty))
        for rel in dirty:
            (ROOT / rel).write_bytes(originals[rel])
        print("⚠️  已强制还原：" + "、".join(dirty))
    else:
        print(f"✅ 还原检查：{len(touched)} 个被碰过的文件与运行前逐字节一致")

    print()
    if fails:
        print("❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"✅ {len(CASES)} 条注入都证明 BUG-0009 那道闸真的在拦。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
