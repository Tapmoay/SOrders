#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_check_dev_spec.py —— **开发规范到底有没有被"接上"**（5 组判据）。

### 为什么要有它

2026-09-27，需求方把《SOrders 新功能开发与既有功能修改规范 v1.0》（三十八节）交进仓库，
要求「**详细写进项目的架构当中，确保每次进行项目之前都能读到**」。

这句话里最难的不是"写进仓库"（那是 `docs/DEVELOPMENT_SPEC.md` 一份文件的事），
而是 **"每次都能读到"**。本项目已经用 git 取过证：一份 **94 KB / 7 份文档的项目地图**
写完之后的 5 个月里，仓库入口文件**一次都没被改过** —— 那份资产对每一个新会话
等于**不存在**（写的人做完就走了，下一个会话从入口冷启动）。

所以这条判据盯的不是"规范写得好不好"，而是**那根线还在不在**：

| 组 | 它扣的是什么 |
| --- | --- |
| 1 | 规范本身：还在、够长、**39 个编号小节 + 3 个附录一个不少** |
| 2 | **三处接线**：`AGENTS.md`（每轮自动进上下文）/ 记忆（key）/ 项目地图 INDEX |
| 3 | **登记簿对账**：`docs/changes/<ID>.md` 文件名 ↔ 内文 ID ↔ README 表，三处一致，无重号 |
| 4 | 模板与每个事项文件的**必填小节**齐全（缺了要写「不适用：<理由>」，⛔ 不许空着） |
| 5 | 四种 ID 前缀都在（`FEAT` / `CHG` / `BUG` / `GOV`） |

### ⛔ 它证不了什么

· 它**不判内容质量**：六问答得糊不糊、`Must Not Change` 写得对不对，机器判不了
  （规范 §33 已把这类"只能人判"的条目逐条列出来）。
· 它**不保证被遵守**。它保证的是「**读得到 + 能被对账**」——
  这是本项目能给"流程纪律"做到的机器形态上限。

### 纪律

**清单是手写的，但配了条数下限**（这与 `_check_report_facts.py` / `_check_reverse_verify_anchors.py` 同一条）：
节数、行数、接线处数、事项数**任一下降到下限以下先报错**，
⛔ 不许出现「扫描坏了 → 一条都没查 → 反而报绿」（本项目栽过 5 次的形状）。

### R3-BOUNDARY-JUSTIFICATION

R3-BOUNDARY-JUSTIFICATION: 这条**没法用边界消除** —— 它管的是"**文档与入口之间的那根线**"，
而线的两端都会独立地动：规范会被改名/搬走，`AGENTS.md` 会被后来的人重排，
`docs/changes/` 会加文件会删文件。
没有任何类型系统或编译期检查能表达"`AGENTS.md` 里那一行链接还在不在"。
「把接线改成生成的」只是把腐烂搬个地方（生成器自己也要有人跑）。
唯一真正的边界是**当场可核** —— 那就是这条判据本身。
第 3 组（登记簿对账）同理：目录即台账，而**人看的表**必须与目录**互相对得上**，
否则下一轮就会出现"README 说做了、目录里没有"。

用法：python _tools/qa/_check_dev_spec.py
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]

SPEC = ROOT / "docs" / "DEVELOPMENT_SPEC.md"
CHANGES = ROOT / "docs" / "changes"
CHANGES_README = CHANGES / "README.md"
CHANGES_TEMPLATE = CHANGES / "_TEMPLATE.md"
AGENTS = ROOT / "AGENTS.md"
INDEX = ROOT / "docs" / "PROJECT_MAP" / "INDEX.md"
CLAIM = ROOT / "docs" / "AI_WORK_CLAIM.md"
CORE_EXT = ROOT / "docs" / "CORE_AND_EXTENSION.md"

#: 规范的**编号小节**必须一个不少（⛔ 硬编码，**不许从规范自己算** ——
#: 那等于"用被判据的东西当判据"：删掉一节，清单跟着少一节，永远绿）。
SPEC_SECTIONS = ["零"] + [
    "一", "二", "三", "四", "五", "六", "七", "八", "九", "十",
    "十一", "十二", "十三", "十四", "十五", "十六", "十七", "十八", "十九", "二十",
    "二十一", "二十二", "二十三", "二十四", "二十五", "二十六", "二十七", "二十八", "二十九", "三十",
    "三十一", "三十二", "三十三", "三十四", "三十五", "三十六", "三十七", "三十八",
]
SPEC_APPENDICES = ["A", "B", "C"]

#: 模板/事项文件的必填小节（照 `docs/changes/_TEMPLATE.md` 的 ① ～ ⑨）。
REQUIRED_PARTS = ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨"]

ID_RE = re.compile(r"^(FEAT|CHG|BUG|GOV)-(\d{4})\.md$")
ID_DECL_RE = re.compile(r"\*\*ID\*\*\s*[：:]\s*`?([A-Z]+-\d{4})`?")

#: 兜底下限 —— 低于这些数就先喊"扫描坏了"，⛔ 不许安静地少查。
MIN_SPEC_LINES = 900
MIN_SPEC_CHARS = 30000
MIN_CHANGES = 1
MIN_WIRING = 8          # AGENTS(3) + INDEX(3) + CLAIM(2) + CORE_EXT(1) - 记忆那一处由人核（见下）
#: 规范在项目地图里至少要有这么多处链接（导航表 + 全量文档目录）。
MIN_SPEC_LINKS_IN_INDEX = 2
MIN_IDS = 4

#: 「不适用」必须带理由：光写三个字等于空着。
NA_RE = re.compile(r"不适用[^\n]{0,12}?[：:]\s*(\S.{1,})")

#: 一个必填小节**短到只剩一句「不适用」**时（字符数低于这个），那句话必须带理由。
#: ⚠️ 为什么不是"只要出现不适用就要理由"：@@BT@@docs/changes/GOV-0001.md@@BT@@ 的 ④/⑤ 里
#: 有逐字段的「不适用」（如 @@BT@@Owner 是谁：不适用@@BT@@），整节正文很长、理由就在正文里；
#: 要求每个字段后面都跟理由只是噪音。要拦的是**整节只有"（不适用）"三个字**那种空壳。
NA_EMPTY_CHARS = 120

bad: list[str] = []
checked = 0


def _ok(msg: str) -> None:
    print("  OK   " + msg)


def _bad(msg: str) -> None:
    global checked
    checked += 1
    print("  BAD  " + msg)
    bad.append(msg)


def _pass() -> None:
    global checked
    checked += 1


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""


def body_of(bodies: dict[str, str], head: str) -> str:
    """取某个 H2 小节的正文（去掉空白行后判空）。"""
    return bodies.get(head, "").strip()


def _h2s(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if ln.startswith("## ")]


def _section_bodies(text: str) -> dict[str, str]:
    """把 H2 切成 `标题 -> 正文`（用于判"这一节是不是空的"）。"""
    out: dict[str, str] = {}
    cur: str | None = None
    buf: list[str] = []
    for ln in text.splitlines():
        if ln.startswith("## "):
            if cur is not None:
                out[cur] = "\n".join(buf)
            cur = ln.strip()
            buf = []
        elif cur is not None:
            buf.append(ln)
    if cur is not None:
        out[cur] = "\n".join(buf)
    return out


# ---------------------------------------------------------------- 第 1 组：规范本身
def group_spec() -> None:
    print("[1] 规范本身")
    if not SPEC.is_file():
        _bad("docs/DEVELOPMENT_SPEC.md 不存在")
        return
    text = SPEC.read_text(encoding="utf-8", errors="replace")
    lines = text.count("\n") + 1
    if lines < MIN_SPEC_LINES:
        _bad("规范只有 " + str(lines) + " 行，低于下限 " + str(MIN_SPEC_LINES) + "（被掏空/读错了？）")
    elif len(text) < MIN_SPEC_CHARS:
        _bad("规范只有 " + str(len(text)) + " 字符，低于下限 " + str(MIN_SPEC_CHARS))
    else:
        _pass()

    heads = _h2s(text)
    missing = [s for s in SPEC_SECTIONS if not any(h.startswith("## " + s + "、") for h in heads)]
    if missing:
        _bad("规范缺 " + str(len(missing)) + " 个编号小节：" + "、".join(missing[:6])
             + ("…" if len(missing) > 6 else ""))
    else:
        _pass()
    missing_ap = [a for a in SPEC_APPENDICES if not any(h.startswith("## 附录 " + a) for h in heads)]
    if missing_ap:
        _bad("规范缺附录：" + "、".join(missing_ap))
    else:
        _pass()

    # 每个编号小节都要有正文（⛔ 只留标题 = 空壳）
    bodies = _section_bodies(text)
    empty = [h for h in bodies
             if any(h.startswith("## " + s + "、") for s in SPEC_SECTIONS) and len(bodies[h].strip()) < 40]
    if empty:
        _bad("有 " + str(len(empty)) + " 个编号小节只有标题没有正文：" + "、".join(e[3:12] for e in empty[:4]))
    else:
        _pass()
    _ok("规范 " + str(lines) + " 行，" + str(len(SPEC_SECTIONS)) + " 个编号小节 + "
        + str(len(SPEC_APPENDICES)) + " 个附录齐全且非空")


# ---------------------------------------------------------------- 第 2 组：三处接线
def group_wiring() -> None:
    print("[2] 接线（少了任何一处，下一个会话就读不到）")
    wiring = 0

    agents = _read(AGENTS)
    if "](docs/DEVELOPMENT_SPEC.md)" not in agents:
        _bad("AGENTS.md 里没有指向 docs/DEVELOPMENT_SPEC.md 的 markdown 链接（入口断了 = 全断）")
    else:
        wiring += 1
    missing_ids = [p for p in ("FEAT-", "CHG-", "BUG-", "GOV-") if p not in agents]
    if missing_ids:
        _bad("AGENTS.md 里缺 ID 前缀：" + "、".join(missing_ids) + "（四种身份必须都在入口说清）")
    else:
        wiring += 1
    if "docs/changes/" not in agents:
        _bad("AGENTS.md 里没有告诉人「事项定义写在哪」（docs/changes/）")
    else:
        wiring += 1

    index = _read(INDEX)
    # ⚠️ 规范在 INDEX 里有**两个**入口：① 顶部导航表 ② 全量文档目录的 A 组。
    #    要求"至少两处"是有意的 —— 只留一处时，另一处就是一条静默失效的引用
    #    （而"我挂过了"正是本项目栽过的那句话）。所以这里数**次数**，不是"在不在"。
    spec_links = index.count("](../DEVELOPMENT_SPEC.md)")
    if spec_links < MIN_SPEC_LINKS_IN_INDEX:
        _bad("docs/PROJECT_MAP/INDEX.md 里指向规范的链接只有 " + str(spec_links) + " 处，少于 "
             + str(MIN_SPEC_LINKS_IN_INDEX) + " 处（导航表 + 全量文档目录都要有）")
    else:
        wiring += 1
    for need, why in (("](../changes/README.md)", "登记簿入口"),
                      ("](../changes/_TEMPLATE.md)", "事项模板")):
        if need not in index:
            _bad("docs/PROJECT_MAP/INDEX.md 里没有" + why + "（从地图侧回不到规范 = 单向引用）")
        else:
            wiring += 1

    claim = _read(CLAIM)
    # ⚠️ 要的是**链接**（@@BT@@](DEVELOPMENT_SPEC.md)@@BT@@），不是"正文里出现过这个文件名"——
    #    后者会被一句"详见 DEVELOPMENT_SPEC.md（我没链）"满足，而那种写法**点不过去**。
    if "](DEVELOPMENT_SPEC.md)" not in claim:
        _bad("docs/AI_WORK_CLAIM.md 没有**链接**到规范（只提文件名不算接线：声明页是动手前第一站）")
    else:
        wiring += 1
    if not re.search(r"第\s*0\s*条|首行带", claim):
        _bad("docs/AI_WORK_CLAIM.md 里没有「声明行首行必须带 ID」这条规则")
    else:
        wiring += 1

    if "](DEVELOPMENT_SPEC.md)" not in _read(CORE_EXT):
        _bad("docs/CORE_AND_EXTENSION.md 没有**链接**到规范（「改哪儿」与「怎么走」必须互相指得到）")
    else:
        wiring += 1

    if wiring < MIN_WIRING:
        _bad("接线处数 " + str(wiring) + " 低于下限 " + str(MIN_WIRING) + "（判据自己可能失效了）")
    else:
        _ok("接线 " + str(wiring) + " 处（AGENTS.md / INDEX.md / AI_WORK_CLAIM.md / CORE_AND_EXTENSION.md）")


# ---------------------------------------------------------------- 第 3 组：登记簿对账
def group_registry() -> tuple[dict[str, str], list[Path]]:
    print("[3] 登记簿对账（目录即台账）")
    files: list[Path] = []
    if CHANGES.is_dir():
        files = sorted(p for p in CHANGES.glob("*.md") if ID_RE.match(p.name))
    if len(files) < MIN_CHANGES:
        _bad("docs/changes/ 里的登记文件只有 " + str(len(files)) + " 份，低于下限 "
             + str(MIN_CHANGES) + "（目录被掏空 / 扫描坏了）")
        return {}, files

    readme = _read(CHANGES_README)
    if not readme:
        _bad("docs/changes/README.md 不存在（登记簿没有索引页，目录里的文件就是孤儿）")
        return {}, files

    declared: dict[str, str] = {}
    for p in files:
        fid = p.name[:-3]
        text = p.read_text(encoding="utf-8", errors="replace")
        m = ID_DECL_RE.search(text)
        if not m:
            _bad(fid + ".md 里找不到「ID：<ID>」声明行（模板里的 **ID** 那一行）")
            continue
        if m.group(1) != fid:
            _bad(fid + ".md 的内文 ID 是 " + m.group(1) + "，与文件名不符（两处说两个身份）")
            continue
        declared[fid] = text
        if ("](" + p.name + ")") not in readme:
            _bad("登记簿 README 里没有 " + p.name + "（加了文件没登记 = 表会骗人）")

    # 反向：README 里链的每个事项文件都得真的在
    ghost = 0
    for m in re.finditer(r"\]\(((?:FEAT|CHG|BUG|GOV)-\d{4}\.md)\)", readme):
        if not (CHANGES / m.group(1)).is_file():
            _bad("登记簿 README 链了不存在的 " + m.group(1) + "（登记了但文件不在）")
            ghost += 1
    if len(declared) == len(files) and not ghost:
        _pass()
    _ok("登记文件 " + str(len(files)) + " 份，" + str(len(declared)) + " 份内文 ID 与文件名一致，README 对账通过")
    return declared, files


# ---------------------------------------------------------------- 第 4 组：必填小节
def _check_parts(label: str, text: str) -> None:
    bodies = _section_bodies(text)
    for part in REQUIRED_PARTS:
        hit = [h for h in bodies if h.startswith("## " + part)]
        if not hit:
            _bad(label + " 缺必填小节 " + part)
            continue
        body = body_of(bodies, hit[0])
        if not body:
            _bad(label + " 的 " + part + " 一节是空的（⛔ 不适用也要写「不适用：<理由>」）")
        elif len(body) < NA_EMPTY_CHARS and "不适用" in body and not NA_RE.search(body):
            _bad(label + " 的 " + part + " 整节只有「不适用」却没有理由")


def group_parts(declared: dict[str, str]) -> None:
    print("[4] 必填小节（模板 + 每一份事项文件）")
    tpl = _read(CHANGES_TEMPLATE)
    if not tpl:
        _bad("docs/changes/_TEMPLATE.md 不存在（没有模板，下一个人会自己另起一份）")
        return
    before = len(bad)
    _check_parts("_TEMPLATE.md", tpl)
    for fid, text in declared.items():
        _check_parts(fid + ".md", text)
    if len(bad) == before:
        _ok("模板与 " + str(len(declared)) + " 份事项文件的 " + str(len(REQUIRED_PARTS)) + " 个必填小节齐全")


# ---------------------------------------------------------------- 第 5 组：四种 ID
def group_ids() -> None:
    print("[5] 四种身份")
    spec = _read(SPEC)
    missing = [p for p in ("FEAT-", "CHG-", "BUG-", "GOV-") if p not in spec]
    if missing or len([p for p in ("FEAT-", "CHG-", "BUG-", "GOV-") if p not in spec]) > 0:
        _bad("规范里缺 ID 前缀：" + "、".join(missing))
    elif MIN_IDS != 4:
        _bad("MIN_IDS 不是 4（判据自己被改坏了）")
    else:
        _ok("四种 ID（FEAT / CHG / BUG / GOV）在规范与入口里都在")


def main() -> int:
    if not SPEC.is_file() and not AGENTS.is_file():
        print("❌ 连规范与入口文件都找不到 —— 环境不对，拒绝出结论")
        return 1

    group_spec()
    group_wiring()
    declared, _files = group_registry()
    group_parts(declared)
    group_ids()

    print("")
    if bad:
        print("❌ 开发规范接线判据：共 " + str(checked) + " 项，" + str(len(bad)) + " 项不成立：")
        for b in bad:
            print("   - " + b)
        print("")
        print("   修法：规范/接线/登记簿是被**一起**改的 —— 别只改一头（那正是本判据存在的理由）。")
        return 1
    print("✅ 开发规范接线判据 " + str(checked) + " 项全部通过：规范齐全、三处接线都在、登记簿对得上。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
