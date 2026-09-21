"""红线：**给模型看的参数表**只有一份实现（`AiWrite.kt` 的 `crudParams` / `AiFieldSpec.paramKind()`）。

## 为什么要有这一条（2026-09-21 精简轮）
声明式动作（`AiWriteMasterData` / `AiWriteBasicData` 里的 `crud(...)` 工厂，以及撤回专用的
`restoreAction(...)`）都要从「目标实体 + 字段」这两份**规格**推出**参数表**，参数表决定：

1. 模型能不能看见这个动作有哪些参数（键名写错它就填不进去）；
2. 每个参数的**类型说法**——`describeForModel` 会把 `${p.kind.cn}` 拼进**贴给模型看的说明书**
   （例如「fee=运费（元）（必填，数字）」）。

原来两个工厂**各自抄了一遍**这段推导与「字段类型 → 参数类型」的映射。它走散的表现是
**两种说法**：同一种字段类型在两组动作里一个说"数字"、一个说"文本"，模型按一处写、另一处不认
—— **两边都不报错**，只是"参数传得不对"。所以推导、映射、以及"谁都得走它"这三件事一起钉住。

## 判据（清单**自己算**）
1. 造 `CrudSpec` 的文件（= 声明式工厂所在文件，**扫出来**，不写死文件名）必须
   `params = crudParams(targets, fields)`；**唯一例外**是撤回专用工厂（同一文件里
   `undoOnly = true`）——它的参数**必须**是 `emptyList()`（模型不该看到撤回动作的参数）；
2. 「字段类型 → 参数类型」的映射**全库只有一处**，且这一处必须把 `AiFieldType` 的**每个取值**
   都映射到（从 `enum class AiFieldType` 自己数），否则"只有一处"只是"写漏了"；
3. 原来的**内联推导**写法（`AiWriteParam(it.param …)` / `AiWriteParam(it.name …)`）不许再出现在
   别的文件里；
4. 反空转：工厂文件 ≥3、映射里的类型数 ≥8（等于枚举里的取值数）；
5. 这份映射必须**还有读者**：`describeForModel` 里那句 `${p.kind.cn}` 在（否则判断已经空转）。

用法：python _tools/ai/_check_ai_write_params.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
AI = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai"
CORE = AI / "AiWrite.kt"

#: 判据刻意用**当时的原文**：谁把它抄回去，这里立刻红。
INLINE_REWRITES = {
    "又自己拼了目标参数（没走 crudParams）": r"AiWriteParam\(it\.param",
    "又自己拼了字段参数（没走 crudParams）": r"AiWriteParam\(it\.name",
}
#: 「字段类型 → 参数类型」映射的第一条（只有映射本体这么写）
MAPPING_SIG = re.compile(r"AiFieldType\.TEXT\s*->\s*AiWriteParamKind\.TEXT")
MAPPING_BODY = re.compile(r"internal fun AiFieldSpec\.paramKind\(\)[\s\S]*?\n\}")


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def field_types(src: str) -> list[str]:
    """从 `enum class AiFieldType` 自己数出所有取值（不手写清单）。"""
    m = re.search(r"enum class AiFieldType\([^)]*\)\s*\{([\s\S]*?)\n\}", src)
    if not m:
        return []
    return re.findall(r"^\s{4}([A-Z][A-Z_]*)\(", m.group(1), re.M)


def main() -> int:
    fails: list[str] = []
    if not CORE.exists():
        print(f"❌ 找不到 {CORE.relative_to(ROOT)}")
        return 1
    core = read(CORE)

    # ---- 声明式工厂 = 真在造 CrudSpec 的文件（清单自己算，不写死文件名）
    factories = sorted(
        (p for p in AI.glob("*.kt") if "CrudSpec(" in read(p) and "data class CrudSpec(" not in read(p)),
        key=lambda p: p.name,
    )
    print(f"声明式工厂（自己算）：{[p.name for p in factories]}")
    if len(factories) < 3:
        fails.append(f"只扫到 {len(factories)} 个造 CrudSpec 的文件（<3）—— 判据在空转")

    for p in factories:
        src = read(p)
        undo_only = "undoOnly = true" in src
        if undo_only:
            # 撤回动作：参数必须为空（模型看不到它，见 AiWriteRestore.kt 的注释）
            if "params = emptyList()," not in src:
                fails.append(f"{p.name}：撤回专用工厂的参数不是 emptyList()（模型会看见撤回动作的参数）")
            if "crudParams(" in src:
                fails.append(f"{p.name}：撤回专用工厂不该走 crudParams（它的参数必须是空的）")
        else:
            n_params = src.count("params = crudParams(targets, fields),")
            if n_params != 1:
                fails.append(
                    f"{p.name}：`params = crudParams(targets, fields)` 出现 {n_params} 次（应为 1）"
                    " —— 参数表又自己拼了一遍"
                )
            if "params = emptyList()," in src:
                fails.append(f"{p.name}：工厂的参数表成了空表（模型会以为这个动作没有参数）")
        for label, pat in INLINE_REWRITES.items():
            if re.search(pat, src):
                fails.append(f"{p.name}：{label}")

    # ---- 映射只有一处，且把枚举里每个取值都映射到
    declaring = sorted(p.name for p in AI.glob("*.kt") if MAPPING_SIG.search(read(p)))
    print(f"「字段类型 → 参数类型」映射的出处（自己算）：{declaring}")
    if declaring != [CORE.name]:
        fails.append(f"映射出现了 {len(declaring)} 处：{declaring}（应当只有 {CORE.name}）")

    types = field_types(core)
    body = MAPPING_BODY.search(core)
    print(f"AiFieldType 的取值（自己数）：{len(types)} 个 —— {'/'.join(types)}")
    if len(types) < 8:
        fails.append(f"只从枚举里数出 {len(types)} 个字段类型（<8）—— 判据在空转")
    if not body:
        fails.append(f"{CORE.name}：找不到 `AiFieldSpec.paramKind()` 的本体")
    else:
        for t in types:
            if f"AiFieldType.{t}" not in body.group(0):
                fails.append(f"映射里漏了字段类型 {t}（模型看到的参数会说错类型）")

    # ---- crudParams 本体：目标与字段都要映射，不许只做一半
    m = re.search(r"internal fun crudParams\([\s\S]*?\n\}", core)
    if not m:
        fails.append(f"{CORE.name}：找不到 `crudParams` 的本体")
    else:
        for part, why in (("targets.map", "目标实体"), ("fields.map", "普通字段")):
            if part not in m.group(0):
                fails.append(f"crudParams 里没有推导{why}（{part}）—— 参数表会缺一整类")

    # ---- 这份映射得有读者：说明书里那句 `${p.kind.cn}`
    if "${p.kind.cn}" not in core:
        fails.append("describeForModel 里不再渲染 ${p.kind.cn} —— 这份映射已经没有读者（判断空转了）")

    if fails:
        print("\n❌ 「给模型看的参数表只有一份实现」被破坏：")
        for f in fails:
            print("   - " + f)
        return 1
    print(
        f"\n✅ 全部通过：{len(factories)} 个声明式工厂都从 {CORE.name} 的 crudParams 取参数表，"
        f"字段类型映射 {len(types)}/{len(types)} 只有一个出处。"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
