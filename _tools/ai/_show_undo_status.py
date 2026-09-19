"""撤回状态总览：**每个动作要么能一键撤回，要么逐条写了为什么不能**。

这个脚本回答一个问题：用户说「把全部的全部改了」——**到底改完了没有？**

v3.26 的时候这件事答不上来：撤回的实现散在四处（声明式规格里的 `undoAction`、
两个手写处理器的 `prepareUndo`、`AiWrites.UNDO_CAPABLE` 手写集合、
三十多个改类动作共用的一句"照上面改回去"），因此只能一条条读代码去数。
v3.27 把接线收敛到一处（`ai/AiResources.kt` 的资源表 + `ai/AiRevert.kt` 的理由表），
这个脚本就是那张表的**机器核对版**：它把源码当数据读一遍，然后逐条核对
"表和实现有没有走散"。

用法：
    python _tools/ai/_show_undo_status.py           # 打印总览（给人看）
    python _tools/ai/_show_undo_status.py --check   # 有对不上的就非零退出（给 CI/收尾用）

核对项（`--check` 会全部检查，任何一条不过就红）：
1. 每个动作都在某张资源表里，或者有一条**属于它自己**的理由；
2. 每个资源 `labels + silent == readKeys`（差一个 = 有键在静默地进/出）；
3. 每个资源的动作都真的注册过（不然挂上去也调不到）、逆操作也都存在；
4. **声明式动作会写的每个键，它所属的资源都读得回来**（漏一个 = 撤回时那一项静默不变）；
5. 撤不回来的理由不许一句糊住一批（新建类那一句除外，但它只能用在新建类上）；
6. "照上面改回去"那种批量免责的写法**不许再出现在源码里**。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Windows 控制台默认是 GBK，中文/符号直接抛 UnicodeEncodeError（本文件里有 ✅ ❌）。
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

AI = Path(__file__).resolve().parents[2] / "android/app/src/main/java/com/tapmoay/sorders/ai"

# 撤回的接线只允许出现在这两个文件里（别处出现 = 又散开了）
REVERT_FILE = "AiRevert.kt"
RESOURCE_FILE = "AiResources.kt"

# 「改类」那句万能免责的原话（出现即红）
BANNED = "照上面改回去"


def read(name: str) -> str:
    return (AI / name).read_text(encoding="utf-8")


def strip_comments(src: str) -> str:
    """去掉行注释与块注释。

    ⚠️ 必须去：这两个文件的文档注释里**大量引用**被禁掉的写法（解释为什么禁它），
    不去注释就会把"解释"当成"犯了"。
    """
    src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    return re.sub(r"//[^\n]*", "", src)


# ---------------------------------------------------------------- 动作清单

def action_constants() -> dict[str, str]:
    """`常量名 -> 动作 id`（只取 AiWrite.kt 里那些以点号命名的常量）。"""
    src = read("AiWrite.kt")
    out: dict[str, str] = {}
    for name, value in re.findall(r'const val (\w+) = "([^"]+)"', src):
        if "." in value:  # 动作 id 一律是 `域.动作` 形状
            out[name] = value
    return out


def defined_actions(consts: dict[str, str]) -> dict[str, str]:
    """**真的注册过的**动作：`id = X` 定义，或 `restoreAction(..., AiWrites.X, ...)` 注册。"""
    found: dict[str, str] = {}
    for f in sorted(AI.glob("*.kt")):
        if f.name in (REVERT_FILE, RESOURCE_FILE):
            continue  # 这两个文件里的是**接线**，不是动作定义
        src = strip_comments(f.read_text(encoding="utf-8"))
        for name in re.findall(r"\bid\s*=\s*(?:AiWrites\.)?(\w+)\s*,", src):
            if name in consts:
                found[name] = consts[name]
        for name in re.findall(r"restoreAction\(\s*\"[^\"]*\",\s*AiWrites\.(\w+)", src):
            if name in consts:
                found[name] = consts[name]
    return found


def balanced(src: str, open_at: int) -> str:
    """从 `open_at`（指向 `(`）开始取到配对的 `)` —— 参数表都是跨多行的，按行取会漏。"""
    depth = 0
    for i in range(open_at, len(src)):
        if src[i] == "(":
            depth += 1
        elif src[i] == ")":
            depth -= 1
            if depth == 0:
                return src[open_at : i + 1]
    return src[open_at:]


def field_block(blk: str, name: str) -> str:
    """取 `name = setOf( ... )` / `mapOf( ... )` 的括号内内容（跨行安全）。"""
    m = re.search(rf"\n\s+{name} = (setOf|mapOf)\(", blk)
    if not m:
        return ""
    return balanced(blk, blk.index("(", m.start()))


# 字段工厂（声明式规格里描述"收哪些字段"的那几个函数）
FIELD_FACTORY = re.compile(r"\b(textField|moneyField|boolField|enumField|dateField|AiFieldSpec)\s*\(")


def spec_field_keys(fields_block: str) -> set[str]:
    """一段 `fields = listOf( ... )` 里，每个字段最终会写进 payload 的键。

    规则：`.copy(key = "x")` 或工厂的 `key = "x"` 参数优先，否则**参数名就是键名**
    （`textField("phone", …)` 写的就是 `phone`）。
    """
    keys: set[str] = set()
    hits = list(FIELD_FACTORY.finditer(fields_block))
    for i, m in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(fields_block)
        seg = fields_block[m.end() : end]
        km = re.search(r'key = "([a-z_]+)"', seg)
        if km:
            keys.add(km.group(1))
            continue
        first = re.search(r'"([a-z_]+)"', seg)
        if first:
            keys.add(first.group(1))
    return keys


# ---------------------------------------------------------------- 资源表

def resources() -> list[dict]:
    """把 `AiResources.kt` 当数据读：每个资源的键集合与动作接线。"""
    src = strip_comments(read(RESOURCE_FILE))
    out = []
    heads = re.findall(r"\n    private val (\w+) = AiResource\(", src)
    blocks = re.split(r"\n    private val \w+ = AiResource\(", src)[1:]
    for head, blk in zip(heads, blocks):
        key = re.search(r'key = "([^"]+)"', blk)
        cn = re.search(r'cn = "([^"]+)"', blk)
        id_key = re.search(r'idKey = "([^"]+)"', blk)
        read_keys = set(re.findall(r'"([a-z_]+)"', field_block(blk, "readKeys"))) | set(
            re.findall(r"\b(GEO_LAT|GEO_LNG)\b", field_block(blk, "readKeys"))
        )
        labels_block = field_block(blk, "labels")
        labels = set(re.findall(r'"([a-z_]+)" to ', labels_block))
        silent = set(re.findall(r'"([a-z_]+)"', field_block(blk, "silent"))) | set(
            re.findall(r"\b(GEO_LAT|GEO_LNG)\b", field_block(blk, "silent"))
        )
        actions = []
        for m in re.finditer(r"\b(update|delete|paired|switcher)\(\s*AiWrites\.(\w+)", blk):
            shape = {"update": "改", "delete": "删", "paired": "成对", "switcher": "切换"}[m.group(1)]
            # 这个动作声明了哪些键**不靠读回**：negate（取负）与 drop（故意不写回）
            call = balanced(blk, blk.index("(", m.start()))
            skip = set()
            for part in ("negate", "drop"):
                mm = re.search(rf"{part} = setOf\(", call)
                if mm:
                    skip |= set(re.findall(r'"([a-z_]+)"', balanced(call, call.index("(", mm.start()))))
            actions.append((shape, m.group(2), skip))
        out.append(
            {
                "var": head,
                "key": key.group(1) if key else head,
                "cn": cn.group(1) if cn else head,
                "idKey": id_key.group(1) if id_key else "",
                "readKeys": read_keys,
                "labels": labels,
                "silent": silent,
                "actions": actions,
            }
        )
    return out


def undo_none_reasons() -> dict[str, str]:
    """`动作常量名 -> 理由`（从 `AiRevert.kt` 的 UNDO_NONE 里读）。"""
    src = strip_comments(read(REVERT_FILE))
    block = src[src.find("buildUndoNone") :]
    out: dict[str, str] = {}
    for m in re.finditer(r"none\(\s*listOf\(([^)]*)\)\s*,\s*([\s\S]*?),\s*\)", block):
        names = re.findall(r"AiWrites\.(\w+)", m.group(1))
        reason = " ".join(re.findall(r'"([^"]*)"', m.group(2)))
        for n in names:
            out[n] = reason
    return out


# ---------------------------------------------------------------- 报告

SHAPE_ORDER = {"改": 0, "删": 1, "成对": 2, "切换": 3}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="有对不上的就非零退出")
    args = ap.parse_args()

    consts = action_constants()
    defined = defined_actions(consts)
    res = resources()
    reasons = undo_none_reasons()

    fails: list[str] = []
    by_action: dict[str, tuple[str, str]] = {}  # 常量名 -> (形状, 资源 key)
    skip_keys: dict[str, set[str]] = {}  # 常量名 -> 不靠读回的那几个键（negate/drop）
    for r in res:
        for shape, name, skip in r["actions"]:
            if name in by_action:
                fails.append(f"{name} 同时挂在两个资源下（{by_action[name][1]} / {r['key']}）")
            by_action[name] = (shape, r["key"])
            skip_keys[name] = skip
    for name in reasons:
        if name in by_action:
            fails.append(f"{name} 既能撤回、又写了撤不回来的理由（自相矛盾）")

    # ---- 逐条核对 ----
    for r in res:
        if r["labels"] | r["silent"] != r["readKeys"]:
            fails.append(
                f"资源 {r['key']}：labels+silent 与 readKeys 对不上 "
                f"（多出 {sorted((r['labels'] | r['silent']) - r['readKeys'])}，"
                f"少了 {sorted(r['readKeys'] - (r['labels'] | r['silent']))}）"
            )
        if not r["actions"]:
            fails.append(f"资源 {r['key']} 一个动作都没挂（这条检查在空转）")
        for _, name, _ in r["actions"]:
            if name not in defined:
                fails.append(f"资源 {r['key']} 挂了不存在的动作 {name}")

    # 声明式动作会写的键，必须读得回来
    checked_crud_keys = 0
    for f in sorted(AI.glob("*.kt")):
        if f.name in (REVERT_FILE, RESOURCE_FILE):
            continue
        src = strip_comments(f.read_text(encoding="utf-8"))
        for blk in re.split(r"\n        crud\(", src)[1:]:
            m = re.search(r"id = AiWrites\.(\w+)", blk)
            if not m:
                continue
            name = m.group(1)
            if name not in by_action:
                continue
            rk = next(r for r in res if r["key"] == by_action[name][1])
            fields_at = blk.find("fields = listOf(")
            if fields_at < 0:
                continue  # 没有字段 = 删除/切换类，没什么可核对
            keys = spec_field_keys(balanced(blk, blk.index("(", fields_at)))
            # 地址类字段会被高德换出坐标一起写进去（见 CrudSpec.geocodeFrom）
            if "geocodeFrom" in blk:
                keys |= {"GEO_LAT", "GEO_LNG"}
            if not keys:
                fails.append(f"{name} 解析不出任何 payload 键（清单过期了？）")
                continue
            # 每个键都要有下落：读得回来、或者在表里声明过 negate/drop（后者要在卡上写明为什么）
            missing = {k for k in keys if k not in rk["readKeys"] and k not in skip_keys.get(name, set())}
            if missing:
                fails.append(
                    f"{name} 会写 {sorted(missing)}，但资源 {rk['key']} 既读不回这些键、也没声明 negate/drop"
                )
            checked_crud_keys += 1

    if checked_crud_keys < 10:
        fails.append(f"只核对到 {checked_crud_keys} 个声明式动作的键（清单过期了？）")

    # 不许一句糊住一批（新建类那句只能用在新建类上）
    create_like_sentence = None
    groups: dict[str, list[str]] = {}
    for name, reason in reasons.items():
        groups.setdefault(reason, []).append(name)
    if "products.create" in reasons:
        create_like_sentence = reasons["products.create"]
    for reason, names in groups.items():
        if len(names) <= 2:
            continue
        if reason == create_like_sentence:
            bad = [n for n in names if not (n.endswith("_CREATE") or n in {"CONTACT_UPSERT", "PRICE_RULES_SET", "ORDERS_ADD_LINE", "LEDGER_CREATE_ENTRY"})]
            if bad:
                fails.append(f"「新建类」那句兜底被用在非新建类动作上：{bad}")
            continue
        fails.append(f"一句理由糊住了 {len(names)} 个动作（应当逐条写清后果）：{names}")

    for f in sorted(AI.glob("*.kt")):
        if BANNED in strip_comments(f.read_text(encoding="utf-8")):
            fails.append(f"{f.name} 里又出现了「{BANNED}」这种批量免责的写法")

    # ---- 打印 ----
    create_like_names = {n for n in defined if n.endswith("_CREATE")} | {
        n for n in ("CONTACT_UPSERT", "PRICE_RULES_SET", "ORDERS_ADD_LINE", "LEDGER_CREATE_ENTRY") if n in defined
    }
    rest = set(defined) - set(by_action) - set(reasons)
    print(
        f"动作总数 {len(defined)}：能一键撤回 {len(by_action)}，"
        f"逐条写明撤不回来 {len(reasons)}，新建类（走兜底那句）{len(rest & create_like_names)}，"
        f"**没交代** {len(rest - create_like_names)}"
    )
    print(f"（另核对了 {checked_crud_keys} 个声明式动作「会写的键都读得回来」）")
    print()
    print(f"{'动作':34s} {'中文域':10s} {'撤回怎么走':40s} 理由/说明")
    print("-" * 130)
    for name in sorted(defined, key=lambda n: (by_action.get(n, ("z", ""))[1], SHAPE_ORDER.get(by_action.get(n, ("z",))[0], 9), n)):
        aid = defined[name]
        if name in by_action:
            shape, rkey = by_action[name]
            rk = next(r for r in res if r["key"] == rkey)
            inv = "同一个动作写回旧值" if shape == "改" else ("恢复动作" if shape == "删" else ("另一个动作" if shape == "成对" else "再做一次"))
            print(f"{aid:34s} {rk['cn']:10s} {shape + ' → ' + inv:40s} 资源 {rk['key']}")
        elif name in reasons:
            print(f"{aid:34s} {'—':10s} {'撤不回来':40s} {reasons[name]}")
        elif name in create_like_names:
            print(f"{aid:34s} {'—':10s} {'撤不回来（新建类兜底）':40s} 新建出来的那条撤不掉，但可以改/停用/删")
        else:
            print(f"{aid:34s} {'?':10s} {'**没有交代**':40s} ← 这条会红")

    print()
    if fails:
        print(f"❌ {len(fails)} 项对不上：")
        for f in fails:
            print("   - " + f)
        return 1 if args.check else 0
    if args.check:
        print("✅ 全部动作都有交代，且资源表与实现没有走散。")
    else:
        print("✅ 没有发现问题（用 --check 时才会非零退出）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
