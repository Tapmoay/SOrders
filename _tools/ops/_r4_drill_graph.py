# -*- coding: utf-8 -*-
"""打印 R4 的**模块依赖图**（指南 §29）：谁依赖谁 / 谁拥有表 / 谁提供能力 / 谁监听事件。

指南 §29 说得很直白：

> 真正的模块化不是「目录结构看起来漂亮」，而是：
> **依赖关系是有限的、可解释的、可验证的。**

⛔ 这一份**不手写**：扩展那半边来自各扩展的清单（`requires` / `provides` / `owns_tables` / `consumes`），
核心那半边来自 `docs/R4_CORE_EXTENSION_MAP.md`（表归属与事件归属都在那儿，由判据核着）。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
MAP = ROOT / "docs" / "R4_CORE_EXTENSION_MAP.md"
sys.path.insert(0, str(ROOT / "backend"))

FENCE = chr(96) * 3


def map_blocks() -> list[dict[str, str]]:
    text = MAP.read_text(encoding="utf-8", errors="replace")
    out: list[dict[str, str]] = []
    for m in re.finditer("^" + FENCE + "capability" + chr(10) + "(.*?)^" + FENCE + "$", text, re.S | re.M):
        item: dict[str, str] = {}
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                item[k.strip()] = v.strip()
        if item.get("id"):
            out.append(item)
    return out


def main() -> int:
    from app.core.extension_registry import discover

    registry = discover()
    blocks = map_blocks()
    core_tables: dict[str, str] = {}
    event_owner: list[tuple[str, str]] = []
    for b in blocks:
        if b.get("class") == "CORE":
            for t in [x.strip() for x in b.get("owns", "-").split(",") if x.strip() and x.strip() != "-"]:
                core_tables[t] = b["id"]
    data = {
        "extensions": [
            {"id": m.id, "kind": m.kind, "provides": list(m.provides), "requires": list(m.requires),
             "owns_tables": list(m.owns_tables), "config": list(m.config), "capability": m.capability}
            for m in registry.all()
        ],
        "core_capabilities": len([b for b in blocks if b.get("class") == "CORE"]),
        "core_tables": len(core_tables),
        "extension_tables": {t: m.id for m in registry.all() for t in m.owns_tables},
        "events_declared": sum(1 for b in blocks if b.get("class") in ("CORE", "EXTENSION_POINT")),
    }
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print()
    print("谁依赖谁（扩展 -> 核心契约）：")
    for m in registry.all():
        print("  " + m.id + " -> " + (", ".join(m.requires) or "（没有声明 requires）"))
    print("谁提供能力：")
    for m in registry.all():
        print("  " + ", ".join(m.provides) + "  <-  " + m.id)
    print("谁拥有表：")
    owned = data["extension_tables"]
    if owned:
        for t, who in sorted(owned.items()):
            print("  " + t + "  <-  " + who)
    else:
        print("  （当前没有扩展拥有任何表 —— 算价与单位换算都是纯计算）")
    print("核心事实表：" + str(len(core_tables)) + " 张（归属见边界图，判据核）")
    del event_owner
    return 0


if __name__ == "__main__":
    raise SystemExit(main())