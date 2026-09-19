# -*- coding: utf-8 -*-
"""红线：`uploads/locations`、`uploads/products` 的无引用图片清理，**判据清单必须是完整的**。

### 为什么这条检查存在（2026-09-19 外部完整检查 C-6 的伴生品）
`image_archive.purge_orphan_images` 会**删文件**，它删不删的唯一判据是
「库里还有没有任何一行引用这个 URL」，而这份清单写在
`REFERENCED_IMAGE_COLUMNS` 里。**漏一列 = 删掉还在用的图，且不可恢复。**

这类"清单靠人记着更新"的坑本项目已经栽过 5 次（见 `AGENTS.md` 的元规则：
凡"要检查哪些文件/哪些方法"的清单，一律让脚本自己算，再加一条数量判据）。
所以这里**自己扫** `backend/app/models/` 里所有带 `url` 的列，任何一个不在
那张表里就报错——**清单过期时先报错，而不是安静地删图**。

### 它同时钉住的三件事
1. 「模型里所有 url 列」⊆「清理判据清单 ∪ 书面排除」；
2. 反向：判据清单里的每一项都还得是**真实存在**的列（防化石：列改名了清单不跟着改，
   那条引用就永远读不出东西，清理会开始误删）；
3. 清理**真的被调用**（`run_daily_retention` 里还在调 `purge_orphan_images`）——
   写了一整套判据但没人调，等于没有治理（本项目"永远红的检查=没有检查"的镜像版本）。

用法：
    python _tools/qa/_check_image_refs.py
"""
from __future__ import annotations

import io
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import refuse_if_injecting, repo_root  # noqa: E402

ROOT = repo_root()
MODELS = ROOT / "backend" / "app" / "models"
ARCHIVE = ROOT / "backend" / "app" / "services" / "image_archive.py"
RETENTION = ROOT / "backend" / "app" / "services" / "data_retention.py"

#: 数量判据：清单自己算，所以先钉"算出来的东西有多少"。
#: 低于下限说明**解析器坏了**（正则会随代码风格变化失配），而不是"项目里没有图片列了"。
MIN_URL_COLUMNS = 8
MIN_REGISTRY_ROWS = 6

#: 故意**不**进清理判据清单的列：键 = "模型.列名"，值 = 为什么。
EXCLUDED: dict[str, str] = {
    "Order.delivery_photo_urls": (
        "送达照片是货损/纠纷的唯一影像证据，生命周期绑在订单上："
        "delete_orders_by_ids 已按订单 id 精确清理（订单行还在就一张都不动）。"
        "改成按引用扫会让'某次引用写坏'直接变成'删掉凭证'，风险明显更大。"
    ),
}

_CLASS_RE = re.compile(r"^class\s+(\w+)\s*\(", re.M)
_ATTR_RE = re.compile(r"^    (\w+)\s*:\s*Mapped\[", re.M)
_REGISTRY_RE = re.compile(r"^\s*\(\s*(\w+)\s*,\s*\"(\w+)\"\s*,\s*(True|False)\s*\)\s*,", re.M)


def _read(p: Path) -> str:
    return io.open(p, encoding="utf-8", errors="replace").read()


def collect_model_url_columns() -> dict[str, str]:
    """扫 `backend/app/models/*.py` → {"模型.列名": "文件:行号"}（只收列名里带 url 的）。"""
    found: dict[str, str] = {}
    for path in sorted(MODELS.glob("*.py")):
        src = _read(path)
        # 按 class 切块：类名 → 该块文本
        marks = [(m.start(), m.group(1)) for m in _CLASS_RE.finditer(src)]
        for i, (pos, cls) in enumerate(marks):
            end = marks[i + 1][0] if i + 1 < len(marks) else len(src)
            for m in _ATTR_RE.finditer(src[pos:end]):
                name = m.group(1)
                if "url" not in name.lower():
                    continue
                line = src[: pos + m.start()].count("\n") + 1
                found[f"{cls}.{name}"] = f"{path.name}:{line}"
    return found


def collect_registry() -> dict[str, str]:
    """从 `image_archive.REFERENCED_IMAGE_COLUMNS` 里抠出 (模型, 列) 对（只看源码，不 import）。"""
    src = _read(ARCHIVE)
    block = src.split("REFERENCED_IMAGE_COLUMNS", 1)[-1]
    block = block.split(")", 1)[0] if "=" not in block.split("\n", 1)[0] else block
    out: dict[str, str] = {}
    for m in _REGISTRY_RE.finditer(block):
        out[f"{m.group(1)}.{m.group(2)}"] = m.group(3)
    return out


def main() -> int:
    if refuse_if_injecting("图片引用清单检查"):
        return 1

    cols = collect_model_url_columns()
    reg = collect_registry()
    errs: list[str] = []

    print(f"模型里带 url 的列 {len(cols)} 个；清理判据清单 {len(reg)} 行；"
          f"书面排除 {len(EXCLUDED)} 条")
    if len(cols) < MIN_URL_COLUMNS:
        errs.append(
            f"只扫到 {len(cols)} 个 url 列（下限 {MIN_URL_COLUMNS}）——解析器失配了，"
            f"不是项目里没有图片列了。修 `_ATTR_RE`/`_CLASS_RE`。"
        )
    if len(reg) < MIN_REGISTRY_ROWS:
        errs.append(
            f"只解析出 {len(reg)} 行判据（下限 {MIN_REGISTRY_ROWS}）——"
            f"`REFERENCED_IMAGE_COLUMNS` 的写法变了或表被改坏了。"
        )

    missing = sorted(k for k in cols if k not in reg and k not in EXCLUDED)
    if missing:
        errs.append(
            "这些列引用 `uploads/` 下的图片，却既不在清理判据清单里、也没有书面排除：\n"
            + "\n".join(f"    · {k}   （{cols[k]}）" for k in missing)
            + "\n  → 要么加进 `image_archive.REFERENCED_IMAGE_COLUMNS`（它会保护这张图不被误删），"
            "\n     要么加进本脚本的 `EXCLUDED` 并写明为什么不用保护。**不许不管**："
            "\n     漏一列的后果是删掉还在用的图片，且不可恢复。"
        )

    stale = sorted(k for k in reg if k not in cols)
    if stale:
        errs.append(
            "清理判据清单里有**不存在**的列（列改名/删了，清单没跟着改）：\n"
            + "\n".join(f"    · {k}" for k in stale)
            + "\n  → 这一条永远读不出引用，清理会开始误删。请同步清单。"
        )

    dead = sorted(k for k in EXCLUDED if k not in cols)
    if dead:
        errs.append("`EXCLUDED` 里有不存在的列（排除理由变成了化石）：" + "、".join(dead))

    ret = _read(RETENTION)
    if "purge_orphan_images(" not in ret:
        errs.append(
            "`data_retention.run_daily_retention` 里没有调用 `purge_orphan_images` —— "
            "判据再全也没人执行，`uploads/locations/` 照样永远堆积。"
        )

    if errs:
        print("\n❌ 图片引用清单检查没通过：\n")
        for e in errs:
            print("  · " + e + "\n")
        return 1
    print(f"✅ {len(cols)} 个图片列全部有归属（{len(reg)} 条保护 + {len(EXCLUDED)} 条书面排除），"
          f"且清理确实被每日治理调用")
    return 0


if __name__ == "__main__":
    sys.exit(main())
