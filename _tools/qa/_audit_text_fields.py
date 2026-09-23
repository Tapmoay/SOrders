"""静态审计：**文本入参有没有上界**（判据与后端同源：上限取自模型列宽）。

## 为什么要它
模糊测试往文本字段里塞 8000 个字符，实测：
- `POST /customers {"kind": "xxx…8000"}` → 200，而列宽是 `String(12)`：生产 MySQL 直接
  `Data too long`（本地 SQLite 照单全收）——**"本地全绿、上线报错"**；
- 若干 `note` / `remark` / `image_url` 这类字段根本没有任何上界，多长都收。

而"太长"这件事**用户能自助修好**（少写几个字），前提是后端说得清是哪个字段、最多多少字。

## 判据（不在这里另写一份清单）
- 待查清单 = **pydantic 自己枚举出来的**输入模型（后缀 Create/Update/Body/In/…）；
- 每个模型的**目标表**由"字段名与列名的重合度"算出来（唯一最佳且 ≥60% 才认），
  不维护"模型 → 表"的手写映射（那种映射一定会随重构走散）；
- 上限依据 = 该列的 `String(N)` 宽度；列是 TEXT（`length=None`）时数据库自己不限，
  所以只要求"声明了上界"，不对宽度;
- **反向约束**：一个字段都没扫到 / 一个带界的都没有 → 判据空转，非零退出。

用法：
```
python _tools/qa/_audit_text_fields.py          # 有缺口就非零退出（可挂 CI）
python _tools/qa/_audit_text_fields.py --all    # 连已保护的字段一起打印
```
"""
from __future__ import annotations

import os
import sys
import typing
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
# 只读审计：把 DB 指到临时文件，避免顺手在仓库里建出 app.db
os.environ.setdefault(
    "DATABASE_URL", "sqlite:///" + str(Path(os.environ.get("TEMP", "/tmp")) / "_audit_text.db")
)
sys.path.insert(0, str(BACKEND))

from annotated_types import MaxLen  # noqa: E402
from pydantic import BaseModel  # noqa: E402

import app.main  # noqa: E402,F401  —— 导入真正的 app：审计只认"应用实际注册的"模型
from app.models.base import Base as OrmBase  # noqa: E402

INPUT_SUFFIX = ("Create", "Update", "Body", "In", "Request", "Patch", "Param")

#: 这些字段**故意**不设上限，理由写在这里（不设就是默认值，不是没人管）。
EXEMPT: dict[str, str] = {
    # 密码：只做哈希入库，长度不是业务字段（且过长由 bcrypt 自己截断/拒绝）
    "password": "密码只做哈希，长度由哈希算法负责（bcrypt 上限 72 字节）",
}


def all_models() -> list[type[BaseModel]]:
    seen: set[type[BaseModel]] = set()
    stack = list(BaseModel.__subclasses__())
    while stack:
        m = stack.pop()
        if m in seen:
            continue
        seen.add(m)
        stack.extend(m.__subclasses__())
    return sorted(seen, key=lambda c: c.__name__)


def table_columns() -> dict[str, dict[str, int | None]]:
    """表名 → {列名: 字符上限}（`None` = 该列是 TEXT，数据库自己不限长度）。"""
    from sqlalchemy import String

    out: dict[str, dict[str, int | None]] = {}
    for table in OrmBase.metadata.tables.values():
        cols: dict[str, int | None] = {}
        for col in table.columns:
            if isinstance(col.type, String):   # Text 是 String 子类，length=None
                cols[col.name] = col.type.length
        out[table.name] = cols
    return out


def target_table(model_name: str, field_names: set[str],
                 tables: dict[str, dict[str, int | None]]) -> tuple[str | None, float]:
    """算这个输入模型写的是哪张表：字段名与列名的**重合度**（唯一最佳且 ≥60%）。

    ⚠️ 为什么不写死"模型名 → 表名"的映射：`AddressCreate` 写的是 `shipper_addresses`、
    `OrderCompleteBody` 写的是 `orders`，靠名字猜必然有一批猜不中，而猜不中会被
    静默当成"没有对应列"（= 这条字段就不查了）。用重合度算，重构后仍然成立。
    """
    best, best_score, tie = None, 0.0, False
    for table, cols in tables.items():
        score = len(field_names & set(cols)) / max(1, len(field_names))
        if score > best_score + 1e-9:
            best, best_score, tie = table, score, False
        elif abs(score - best_score) < 1e-9 and score > 0:
            tie = True
    if best is None or best_score < 0.6 or tie:
        # 兜底：模型名去掉后缀 = 表名（单数/复数两种写法）
        base = ""
        for suffix in INPUT_SUFFIX:
            if model_name.endswith(suffix):
                base = model_name[: -len(suffix)].lower()
                break
        for table in tables:
            if table in (base, base + "s") or table.replace("_", "") in (base, base + "s"):
                return table, 1.0
        return None, best_score
    return best, best_score


def scalar_types(ann: object) -> set[object]:
    out: set[object] = set()
    for arg in typing.get_args(ann) or (ann,):
        out |= scalar_types(arg) if typing.get_args(arg) else {arg}
    return out


def has_str(ann: object) -> bool:
    """注解里有没有**作为值**的 str。

    ⚠️ `dict[str, Any]` 里的 `str` 是**键**的类型，不是要审的文本：
    第一版没区分，于是 `notification.payload`（一个 JSON 对象）被当成文本字段报了出来。
    这类字段的大小不是"文字太长"的问题（那是请求体大小限制的事），不该混在一起。
    """
    if "dict" in str(ann):
        args = typing.get_args(ann)
        # dict[K, V]：只看 V
        return any(has_str(a) for a in args[1:]) if len(args) >= 2 else False
    return str in scalar_types(ann)


def bound_of(field) -> int | None:
    for m in field.metadata:
        if isinstance(m, MaxLen):
            return m.max_length
    return None


def pattern_of(field) -> str | None:
    for m in field.metadata:
        p = getattr(m, "pattern", None)
        if p:
            return str(p)
    return None


def item_bound(ann: object) -> int | None:
    """列表元素自己的长度上界（`list[Url]` 里的 `Annotated[str, StringConstraints(max_length=N)]`）。

    ⚠️ 只给列表加 `max_length=` 是不够的：那只限**条数**，不限制"每一条有多长"——
    9 条各 10 万字的 URL 照样能塞进一个 TEXT 列。
    """
    for arg in typing.get_args(ann):
        ml = getattr(arg, "max_length", None)
        if isinstance(ml, int):
            return ml
        for meta in typing.get_args(arg):     # Annotated[str, StringConstraints(...)]
            ml = getattr(meta, "max_length", None)
            if isinstance(ml, int):
                return ml
        if typing.get_args(arg):
            ml = item_bound(arg)
            if ml:
                return ml
    return None


def main() -> int:
    # ⛔ `--check` = **进必跑清单的凭据**（2026-09-23 第 18 轮补）：`_check_all.py` 的清单自己算
    #    （`_check_*.py` 或声明了 `--check` 的脚本），而这个脚本叫 `_audit_*` 又没有 `--check`
    #    → 它报的 4 条（2 条超列宽 + 2 条无上界）**一直没人跑**（子代理手动跑才发现）。
    show_all = "--all" in sys.argv
    check = "--check" in sys.argv
    tables = table_columns()
    gaps: list[str] = []
    too_big: list[str] = []
    patterned: list[str] = []
    tensor: list[str] = []
    ok: list[str] = []
    n_fields = 0

    for model in all_models():
        if not any(model.__name__.endswith(s) for s in INPUT_SUFFIX):
            continue
        if model.__module__.startswith(("fastapi", "pydantic", "starlette")):
            continue  # 框架自己的模型（如 OAuth2 表单）不是我们的入参
        names = {n for n, f in model.model_fields.items() if has_str(f.annotation)}
        table, score = target_table(model.__name__, set(model.model_fields), tables)
        cols = tables.get(table or "", {})
        for name, field in model.model_fields.items():
            if not has_str(field.annotation):
                continue
            n_fields += 1
            where = f"{model.__module__.split('.')[-1]}.{model.__name__}.{name}"
            col_known = name in cols
            col = cols.get(name)
            in_list = "list" in str(field.annotation)
            if name in EXEMPT:
                ok.append(f"{where}（豁免：{EXEMPT[name]}）")
                continue
            limit = bound_of(field)
            pat = pattern_of(field)
            if limit is None and pat:
                # 全锚定的 pattern（^…$）= 只接受那几种写法，长度天然有界（枚举值）
                if pat.startswith("^") and pat.endswith("$"):
                    patterned.append(f"{where}  pattern={pat}")
                    continue
            if in_list and limit is None:
                tensor.append(f"{where}  列表本身没有条数上界（{field.annotation}）")
                continue
            if in_list and item_bound(field.annotation) is None:
                tensor.append(f"{where}  列表**元素**没有长度上界（{field.annotation}）")
                continue
            if limit is None:
                gaps.append(
                    f"{where}  目标表={table or '?'}(重合度 {score:.0%})  "
                    f"列={'String(%s)' % col if col else ('TEXT' if col_known else '无对应列')}"
                )
                continue
            if col_known and col is not None and limit > col:
                too_big.append(f"{where}  声明 {limit} > 列宽 {col}（生产 MySQL 会 Data too long）")
                continue
            ok.append(f"{where}  声明 {limit}"
                      + (f" ≤ 列宽 {col}" if col else ("（列是 TEXT）" if col_known else "（无对应列）")))

    print(f"文本入参字段 {n_fields} 个（模型清单由 pydantic 自己算，不手写）")
    print(f"  有上界：{len(ok)}    pattern 枚举：{len(patterned)}    "
          f"没有上界：{len(gaps)}    上界超列宽：{len(too_big)}    列表无条数上界：{len(tensor)}")
    if show_all:
        for w in ok:
            print(f"  ✓ {w}")
    if patterned:
        print("\n由 `^…$` pattern 限定取值（长度天然有界）的字段：")
        for w in patterned:
            print(f"  ✓ {w}")
    if tensor:
        print("\n列表字段本身没有条数上界：")
        for w in tensor:
            print(f"  ✗ {w}")
    if too_big:
        print("\n上界比数据库列还宽（生产 MySQL 会 Data too long）：")
        for w in too_big:
            print(f"  ✗ {w}")
    if gaps:
        print("\n没有任何上界（多长都收）：")
        for w in gaps:
            print(f"  ✗ {w}")

    # 反空转：判据必须真的扫到了东西，否则"全绿"什么也不能证明
    if n_fields < 50 or not ok:
        print(f"\n⛔ 判据空转：只扫到 {n_fields} 个字段 / 有界 {len(ok)} 个——先修这个脚本。")
        return 3
    bad = len(gaps) + len(too_big) + len(tensor)
    if check and not show_all:
        # 必跑模式下只印一行结论（`_check_all.py` 把每个脚本的输出收进一张表）
        print(
            f"{'✅' if not bad else '❌'} 文本/取值字段 {n_fields} 个：有界 {len(ok)}"
            f"、pattern 限定 {len(patterned)}、没上界 {len(gaps)}、超列宽 {len(too_big)}、"
            f"列表无条数上界 {len(tensor)}"
        )
        return 2 if bad else 0
    return 2 if (gaps or too_big or tensor) else 0

if __name__ == "__main__":
    sys.exit(main())
