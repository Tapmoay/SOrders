#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_check_r4_closeout.py —— R4 收尾的两组判据：**证据索引不许烂** + **诊断端点不许长成业务 API**。

### 为什么要有它

`docs/R4_EVIDENCE_INDEX.md`（P5 的一页证据索引）的规矩是：
**每一行必须有一个真实存在的文件 + 一个真实存在的入口**。
但「写了」和「还在」是两件事 —— 文件被改名 / 脚本被搬走之后，索引会变成一张
**看起来很权威、其实全是死链**的表。本项目对这件事有明确态度（`AGENTS.md`：
「过期地图比没有地图更糟」；`_tools/qa/_check_report_facts.py` 是同一想法的 R3 版）。

### 判据（三组）

1. **索引本身**：文件在、行数 ≥ `MIN_ROWS`（扫描坏了先喊，⛔ 不许安静地一条都不查）；
2. **每一行**：至少一个证据文件 + 一个入口；反引号里的路径**必须真的存在**（支持 `*` 通配）；
3. **诊断端点不许长成业务 API**（R4-49 §四 的生命周期裁决）：
   · 只挂 GET（⛔ 不许出现 POST/PUT/PATCH/DELETE）；
   · ⛔ App 源码里一个引用都不许有（它只是 Internal Diagnostic Surface）；
   · 必须仍在 `router.py` 里被挂上，且必须出现在端点索引里。

### ⛔ 它证不了什么

· 它**不重跑**索引里那些重命令（那是各条命令自己的事，见 `_check_all.py --deep`）；
   这里只保证**引用没烂**。
· 它证不了「索引里那句话描述得准确」—— 一句话有没有说过头，机器判不了。

### R3-BOUNDARY-JUSTIFICATION

R3-BOUNDARY-JUSTIFICATION: 这条**没法用边界消除** —— 它管的是「索引里那句话指向的东西还在不在」，
而索引是**手写**的、被它指向的文件是**会改名/会搬走**的。
「把索引改成生成的」只是把腐烂搬个地方：生成器自己也维护着一份映射。
唯一真正的边界是「引用必须当场可核」—— 那就是这条判据本身。
第 3 组（诊断端点不许长成业务 API）同理：它守的不是某个函数，而是一条**会随时间漂移的定位**，
没有任何类型/编译期检查能表达「它只是诊断面」这件事。

用法：python _tools/qa/_check_r4_closeout.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
INDEX = ROOT / "docs/R4_EVIDENCE_INDEX.md"
DIAG = ROOT / "backend" / "app" / "api" / "v1" / "diagnostics.py"
ROUTER = ROOT / "backend" / "app" / "api" / "v1" / "router.py"
ENDPOINT_INDEX = ROOT / "docs" / "PROJECT_MAP" / "08A_ENDPOINT_INDEX.md"
ANDROID = ROOT / "android"

#: 索引至少要有这么多行 —— ⛔ 扫描坏了要先喊，不许「一条都没查」也报绿。
MIN_ROWS = 20

_TOKEN_RE = re.compile(r"`([^`]+)`")
_PATH_EXT = (".py", ".json", ".md", ".kt", ".txt", ".jsonl")


def _is_path(t: str) -> bool:
    return "/" in t and t.endswith(_PATH_EXT)


def _exists(t: str) -> bool:
    if "*" in t:
        return len(list(ROOT.glob(t))) > 0
    return (ROOT / t).exists()


def _rows(text: str) -> list[list[str]]:
    out: list[list[str]] = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 3:
            continue
        if set("".join(cells)) <= set("-: "):
            continue
        if cells[0] in ("结论", "Claim"):
            continue
        out.append(cells)
    return out


def main() -> int:
    bad: list[str] = []
    seen = 0

    # ---------------- 第 1 组：索引本身 ----------------
    if not INDEX.exists():
        print("❌ 证据索引不在：" + str(INDEX))
        return 1
    text = INDEX.read_text(encoding="utf-8")
    rows = _rows(text)
    seen += 1
    if len(rows) < MIN_ROWS:
        bad.append("证据索引只有 " + str(len(rows)) + " 行（< " + str(MIN_ROWS)
                   + "）—— ⛔ 扫描坏了先喊，不许安静地一条都不查")
        print("  BAD  索引行数 -> " + str(len(rows)))
    else:
        print("  OK   索引行数 -> " + str(len(rows)) + " 行")

    # ---------------- 第 2 组：每一行的文件与入口 ----------------
    missing: list[str] = []
    for cells in rows:
        toks = _TOKEN_RE.findall("|".join(cells))
        # ⚠️ `python xxx.py` 这种 token **同时**满足 _is_path —— 第一版没排掉，
        #    于是拿带 "python " 前缀的整串去 exists()，23 处全报「引用烂了」（判据自己错）。
        entries = [t for t in toks if t.startswith("python ")]
        paths = [t for t in toks if _is_path(t) and not t.startswith("python ")]
        label = cells[0][:34]
        if not paths:
            bad.append("第 " + label + " 行没有证据文件")
        if not entries:
            bad.append("第 " + label + " 行没有复现入口")
        # ⚠️ 入口常常带参数（`python x.py --check`）—— 只取**第一个 token** 当路径；
        #    第一版整串拿去 exists()，13 处带参数的入口全报「引用烂了」（判据自己错）。
        for p in paths + [e[len("python "):].strip().split()[0] for e in entries]:
            if not _exists(p):
                missing.append(label + " -> " + p)
    seen += 1
    if missing:
        print("  BAD  引用烂了 " + str(len(missing)) + " 处：")
        for m in missing:
            print("        " + m)
        bad.append("索引里有 " + str(len(missing)) + " 处引用指向不存在的文件/入口")
    else:
        print("  OK   每一行的证据文件与入口都真的在 -> " + str(len(rows)) + " 行")

    # ---------------- 第 3 组：诊断端点不许长成业务 API ----------------
    seen += 1
    diag_problems: list[str] = []
    if not DIAG.exists():
        diag_problems.append("diagnostics.py 不在了")
    else:
        src = DIAG.read_text(encoding="utf-8")
        if "@router.get(" not in src:
            diag_problems.append("它没有 GET 路由")
        for verb in ("post", "put", "patch", "delete"):
            if "@router." + verb + "(" in src:
                diag_problems.append("它挂了写动词 " + verb.upper())
        if "require_permission(" not in src:
            diag_problems.append("它没有走权限边界（⛔ 不许匿名）")
    if ROUTER.exists() and "include_router(diagnostics.router)" not in ROUTER.read_text(encoding="utf-8"):
        diag_problems.append("router.py 里没有挂它")
    if ENDPOINT_INDEX.exists() and "diagnostics/orders/" not in ENDPOINT_INDEX.read_text(encoding="utf-8"):
        diag_problems.append("端点索引里没有它（产物过期）")
    app_hits: list[str] = []
    if ANDROID.exists():
        for p in ANDROID.rglob("*.kt"):
            if p.is_file() and "diagnostics" in p.read_text(encoding="utf-8", errors="ignore"):
                app_hits.append(str(p.relative_to(ROOT)))
    if app_hits:
        diag_problems.append("App 源码里引用了它（它只是 Internal Diagnostic Surface）："
                             + "、".join(app_hits[:3]))
    if diag_problems:
        print("  BAD  诊断端点跑偏了：")
        for m in diag_problems:
            print("        " + m)
        bad.extend(diag_problems)
    else:
        print("  OK   诊断端点仍是一条只读的 Internal Diagnostic Surface（GET / 权限边界 / App 零引用）")

    print("")
    if bad:
        print("❌ R4 收尾判据 " + str(seen) + " 组，" + str(len(bad)) + " 条不成立：")
        for b in bad:
            print("   - " + b)
        return 1
    print("✅ " + str(seen) + " 组判据全部通过：证据索引每一行的文件与入口都在、诊断端点仍是一条只读诊断面。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())