"""红线：**AI 声明式 CRUD 的「声明」与「实现」不许走散**（2026-09-19 审计「声明式 CRUD」专项）。

## 这一条是子代理给的通用经验，固化成判据
> 抓「静默丢字段」最快的一刀是**机械对账每个 crud 的字段键 vs 它 commit 里 pick() 的键集合**。

这条红线做的是它的**下一半**：`pick()` 把键放进了 payload，但**数据源实现里没有把它搬进请求**
—— 模型说了、卡片上也写了，实际发出去的请求里根本没有那个键。本轮实测的那条（高·写错钱）：

```
DRIVER_RULE_KEYS 里有 piece_unit / commission_base，规格里也有对应字段，
声明式那层也 pick 进了 payload —— 但 updateDriverRule 的 DTO 构造里没有这两行。
模型说「把计件方式改成每件」→ 卡片写「每件：3 元」→ 请求里没有这个键 → 规则还是「每单」。
```

## 判据（清单自己算）
1. 从四个规格文件里解析出所有 `p.pick(<键集合>)`（键集合可以写字面量，也可以是命名的 val）；
2. 找到同一个 lambda 里调的 `ds.<函数名>(`，再到 `AiWriteService.kt` / `AiWriteCrudHandlers.kt`
   里找那个函数的实现体；
3. 实现体里必须出现**每一个**键（`fields.str("k")` / `fields.bool("k")` / `fields.req("k")` …），
   除非在 `KEY_CONSUMED_BY_OTHER_MEANS` 里写了理由（例如"这个键是给人看的、不进请求"）；
4. 另加两条定点判据（本轮修的两条）：客户建档不许提供"是不是批发商"开关（写的是没人读的列）、
   分类位置必须走 reorder（只写绝对值会撞车）。

用法：python _tools/qa/_check_ai_declarative_crud.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import ai_write_source  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
AI = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai"
SPEC_FILES = ("AiWriteBasicData.kt", "AiWriteMasterData.kt", "AiWritePricing.kt",
              "AiWriteSettlementHandlers.kt")
IMPL_FILES = ("AiWriteService.kt", "AiWriteDataSource.kt", "AiWriteJson.kt", "AiWriteCrudHandlers.kt", "AiWriteOrderHandlers.kt",
              "AiWriteOrderLineHandlers.kt", "AiWriteLedgerHandlers.kt",
              "AiWriteNotificationHandlers.kt")

#: 允许"pick 进来的键没在实现里出现"的例外 —— 键 `函数.key`，值=理由。
KEY_CONSUMED_BY_OTHER_MEANS: dict[str, str] = {}

fails: list[str] = []
passes = 0


def ok(label: str, cond: bool, detail: str = "") -> None:
    global passes
    if cond:
        passes += 1
        print(f"  [OK]   {label}")
    else:
        fails.append(label + (f" —— {detail}" if detail else ""))
        print(f"  [FAIL] {label}" + (f" —— {detail}" if detail else ""))


def strip_kt(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"(?m)^\s*//.*$", "", src)
    src = re.sub(r"@\w+(\([^)]*\))?", lambda m: " " * len(m.group(0)), src)
    return src


def named_key_sets(text: str) -> dict[str, set[str]]:
    """`private val XXX_KEYS = setOf("a", "b")` → {XXX_KEYS: {a,b}}。"""
    out: dict[str, set[str]] = {}
    for m in re.finditer(r"val (\w*KEYS)\s*=\s*setOf\(([^)]*)\)", text, re.S):
        out[m.group(1)] = set(re.findall(r'"([^"]+)"', m.group(2)))
    return out


def spec_picks(rel: str) -> list[tuple[int, str, set[str]]]:
    """[(行号, ds 函数名, 键集合)] —— 只取 `p.pick(...)`（**部分更新**那条路）。

    ⚠️ **已知覆盖边界**（本轮试过扩到"创建类动作的字段表"，结果是**假阳性一堆**，已回退）：
    创建类动作是 `ds.createX(p)`（整个 payload 交给数据源），要算它的键集合得先解析
    `textField/moneyField/positionField/AiFieldSpec` 这些 helper 内部把 name 映射成什么 key
    （`positionField` → `sort_order`、`moneyField(..., key=…)`）—— 那些映射写在 helper 定义里，
    不在调用点上。半吊子地按"字段名 = key"猜，会把 `position`/`price`/`user_id` 这类
    全都误报成"没搬"（实测 9 处假阳性），所以这一版**只保留 pick 那条路**（它已经抓到
    `updateVehicle` 的化石键 `driver_id`、以及把 `piece_unit`/`commission_base` 丢掉的那条高）。
    要补齐创建侧，正确做法是先解析 helper 定义（`_tools/ai/_write_coverage.py` 已经在做类似的映射）。
    """
    src = strip_kt((AI / rel).read_text(encoding="utf-8"))
    sets = named_key_sets(src)
    out: list[tuple[int, str, set[str]]] = []
    for m in re.finditer(r"ds\.(\w+)\(([^;]*?)\)\s*\}", src, re.S):
        fn, args = m.group(1), m.group(2)
        keys: set[str] = set()
        for pm in re.finditer(r"pick\(\s*(?:setOf\(([^)]*)\)|(\w+))\s*\)", args, re.S):
            if pm.group(1) is not None:
                keys |= set(re.findall(r'"([^"]+)"', pm.group(1)))
            else:
                keys |= sets.get(pm.group(2) or "", set())
        if keys:
            lineno = src[: m.start()].count("\n") + 1
            out.append((lineno, fn, keys))
    return out


def impl_body(fn: str) -> str | None:
    for rel in IMPL_FILES:
        p = AI / rel
        if not p.exists():
            continue
        src = strip_kt(p.read_text(encoding="utf-8"))
        m = re.search(rf"override suspend fun {re.escape(fn)}\(", src)
        if m is None:
            continue
        rest = src[m.end():]
        nxt = re.search(r"\n    (?:override suspend )?fun \w+\(", rest)
        return rest[: nxt.start()] if nxt else rest
    return None


def main() -> int:
    total = 0
    print("① pick 进 payload 的键，实现里必须真的搬进请求")
    for rel in SPEC_FILES:
        if not (AI / rel).exists():
            fails.append(f"找不到规格文件 {rel}（改名了？判据要跟着改，不许静默跳过）")
            print(f"  [FAIL] 找不到 {rel}")
            continue
        for lineno, fn, keys in spec_picks(rel):
            body = impl_body(fn)
            if body is None:
                fails.append(f"{rel}:{lineno} 调了 ds.{fn}(…)，但找不到它的实现")
                print(f"  [FAIL] ds.{fn} 找不到实现（{rel}:{lineno}）")
                continue
            total += 1
            missing = sorted(
                k for k in keys
                if f'"{k}"' not in body and f"{fn}.{k}" not in KEY_CONSUMED_BY_OTHER_MEANS
            )
            ok(
                f"{rel}:{lineno} ds.{fn}(…) 的 {len(keys)} 个键都被实现消费",
                not missing,
                "实现里没搬的键：" + "、".join(missing)
                + "（模型说了、卡片也写了，请求里却没有 → 静默不生效）",
            )
    ok("扫到 >=8 处 pick（清单自己算，防解析失效后空转）", total >= 8, f"实际 {total}")

    print("\n② 客户建档不许提供「是不是批发商」开关（那一列全后端没人读）")
    basic = strip_kt((AI / "AiWriteBasicData.kt").read_text(encoding="utf-8"))
    m = re.search(r"CUSTOMER_CREATE(.*?)\n        \}", basic, re.S)
    cust = m.group(1) if m else ""
    ok("新增客户的动作里没有 member 开关",
       'boolField("member"' not in cust,
       "写了 `Customer.is_member` —— 而读侧判据是 `User.is_member`，等于给了一张改不动的卡")
    ok("卡片如实写出「同号会沿用」的规则", "沿用" in cust)

    print("\n③ 分类「排第 N 位」必须走 reorder（只写绝对值会撞车）")
    svc = strip_kt(ai_write_source(ROOT))
    for fn in ("createProductCategory", "updateProductCategory"):
        m = re.search(rf"override suspend fun {re.escape(fn)}\(.*?\n    \}}", svc, re.S)
        body = m.group(0) if m else ""
        ok(f"{fn} 把位置交给 moveCategoryTo（而不是只写 sort_order）",
           "moveCategoryTo(" in body)
    ok("moveCategoryTo 真的调了 reorder（整份顺序提交）",
       re.search(r"private suspend fun moveCategoryTo\(.*?repo\.reorderProductCategories\(",
                 svc, re.S) is not None)

    print("\n" + "=" * 60)
    if fails:
        print(f"❌ {len(fails)} 项不通过：")
        for f in fails:
            print("   - " + f[:200])
        return 1
    print(f"✅ 全部 {passes} 项通过：声明与实现没有走散。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
