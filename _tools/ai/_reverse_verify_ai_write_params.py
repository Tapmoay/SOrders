"""反向验证 `_check_ai_write_params.py` 那条判据**真的会红**。

## 为什么要配反向验证
「给模型看的参数表只有一份实现」这条判据的坏法有两种：**判据自己写歪**（清单写死成两个文件名、
正则匹配不上真实写法）→ 恒绿；或者**只钉住了一半**（只查"有没有内联"，不查"映射补没补全"）。
而它守的破坏全是**静默**的：

| 破坏 | 静默后果 |
|---|---|
| 工厂的参数表退回内联推导 | 同一种字段类型在两组动作里两种说法（一处"数字"、一处"文本"），模型按一处写、另一处不认 |
| 别的文件里又抄一份映射（没人调用，编译照过） | 下一次有人照着这份改，两份就开始走散 —— 而当场没有任何症状 |
| `crudParams` 只推导目标、丢掉字段 | 模型看到的动作**一个字段参数都没有**（它会以为这个动作只需要一个名字） |
| 映射漏一个字段类型 | 那个类型的参数在说明书里没有类型（模型只能猜），而 `else` 分支还会让编译器闭嘴 |
| 声明式工厂的参数表成了空表 | 同上，且**一个报错都没有**（卡片摘要照常渲染） |

## 现场保护（复用公共机制，不另造一套）
· `_airepo.refuse_if_injecting` —— 别人的反向验证正在跑时拒绝出结论；
· `_airepo.lock_reverse_verify` —— 上锁期间并发的**检查**会拒绝出结论；
· `_airepo.take_snapshot` / `restore_snapshot` —— 被杀在半路时的整目录兜底；
· 每个文件另做**逐字节**还原，跑完自检 sha256（一个字节都不能变，换行风格原样带回）。

用法：python _tools/ai/_reverse_verify_ai_write_params.py
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _airepo import (  # noqa: E402
    lock_reverse_verify,
    refuse_if_injecting,
    repo_root,
    restore_snapshot,
    snapshot_dir,
    take_snapshot,
    unlock_reverse_verify,
)

ROOT = repo_root()
CHECK = HERE / "_check_ai_write_params.py"
AI = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai"
CORE = AI / "AiWrite.kt"
BASIC = AI / "AiWriteBasicData.kt"
MASTER = AI / "AiWriteMasterData.kt"

PARAMS_LINE = "        params = crudParams(targets, fields),"

#: 一份"没人调用的映射副本"：编译照过、运行照旧，只有判据看得见
MAPPING_COPY = """    private fun AiFieldSpec.kindCopy(): AiWriteParamKind = when (type) {
        AiFieldType.TEXT -> AiWriteParamKind.TEXT
        AiFieldType.MONEY, AiFieldType.COUNT, AiFieldType.DELTA, AiFieldType.NON_NEGATIVE ->
        AiWriteParamKind.NUMBER
        AiFieldType.DATE -> AiWriteParamKind.DATE
        AiFieldType.BOOL -> AiWriteParamKind.TEXT
        AiFieldType.ENUM -> AiWriteParamKind.ENUM
    }

"""

#: (说明, 文件, 原文, 替换成, 期望出现在失败清单里的关键字)
MUTATIONS: list[tuple[str, Path, str, str, str]] = [
    (
        "① 运费模板那一侧的工厂退回内联推导（与商品/地址那侧的映射开始走散）",
        MASTER,
        PARAMS_LINE,
        "        params = targets.map {\n"
        "            AiWriteParam(it.param, it.cn, it.required, AiWriteParamKind.TEXT, it.hint)\n"
        "        },\n",
        "又自己拼了目标参数",
    ),
    (
        "② 另一个文件里又抄一份映射（没人调用、编译照过 —— 下一次就照着这份改）",
        MASTER,
        "    private fun crud(",
        MAPPING_COPY + "    private fun crud(",
        "映射出现了 2 处",
    ),
    (
        "③ crudParams 只推导目标、把字段那一半丢了（模型看到的动作没有字段参数）",
        CORE,
        "    targets.map { AiWriteParam(it.param, it.cn, it.required, AiWriteParamKind.TEXT, it.hint) } +\n"
        "        fields.map { AiWriteParam(it.name, it.cn, it.required, it.paramKind(), it.hint, it.enumValues) }",
        "    targets.map { AiWriteParam(it.param, it.cn, it.required, AiWriteParamKind.TEXT, it.hint) }",
        "crudParams 里没有推导普通字段",
    ),
    (
        "④ 映射漏掉「增减量」，并用 else 让编译器闭嘴（那个类型的参数没有类型说法）",
        CORE,
        "    AiFieldType.MONEY, AiFieldType.COUNT, AiFieldType.DELTA, AiFieldType.NON_NEGATIVE ->\n"
        "        AiWriteParamKind.NUMBER\n"
        "    AiFieldType.DATE -> AiWriteParamKind.DATE\n"
        "    AiFieldType.BOOL -> AiWriteParamKind.TEXT\n"
        "    AiFieldType.ENUM -> AiWriteParamKind.ENUM",
        "    AiFieldType.MONEY, AiFieldType.COUNT, AiFieldType.NON_NEGATIVE ->\n"
        "        AiWriteParamKind.NUMBER\n"
        "    AiFieldType.DATE -> AiWriteParamKind.DATE\n"
        "    AiFieldType.BOOL -> AiWriteParamKind.TEXT\n"
        "    AiFieldType.ENUM -> AiWriteParamKind.ENUM\n"
        "    else -> AiWriteParamKind.TEXT",
        "映射里漏了字段类型 DELTA",
    ),
    (
        "⑤ 地址那一侧的工厂参数表成了空表（模型以为这个动作没有参数）",
        BASIC,
        PARAMS_LINE,
        "        params = emptyList(),\n",
        "工厂的参数表成了空表",
    ),
]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run_check() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    if refuse_if_injecting("AI 参数表反向验证"):
        return 1
    if not CHECK.exists():
        print(f"❌ 找不到 {CHECK}（红线被改名/搬走了？）")
        return 1

    touched = sorted({m[1] for m in MUTATIONS})
    missing = [str(p) for p in touched if not p.exists()]
    if missing:
        print(f"❌ 注入点文件不存在：{missing}")
        return 1
    before = {p: sha(p) for p in touched}

    bad = 0
    lock_reverse_verify()
    try:
        n = take_snapshot()
        print(f"✅ 已上锁并拍快照（{n} 个文件）：这期间不要改源码")

        code, out = run_check()
        if code != 0:
            print("❌ 前提不成立：源码完好时这条红线就没过\n" + out[-1200:])
            return 1
        print("✅ 前提：源码完好时红线是绿的")

        for label, path, old, new, expect in MUTATIONS:
            raw = path.read_bytes()
            src = raw.decode("utf-8")
            if src.count(old) != 1:
                print(f"  [SKIP] {label} —— 原文出现 {src.count(old)} 次（判据该更新了）")
                bad += 1
                continue
            path.write_text(src.replace(old, new), encoding="utf-8", newline="")
            try:
                code, out = run_check()
            finally:
                path.write_bytes(raw)          # ★ 逐字节还原（含换行风格）
            fails = [ln.strip() for ln in out.splitlines() if "被破坏" in ln or ln.strip().startswith("- ")]
            got = next((ln for ln in fails if expect in ln), None)
            hit = code != 0 and got is not None
            print(f"  [{'OK' if hit else 'MISS'}] 注入：{label}")
            print(f"         抓它的判据：{got.strip('- ').strip() if got else '（没有任何判据承认这条注入）'}")
            print(f"         退出码 {code}")
            if not hit:
                for f in fails[:4]:
                    print(f"            · {f.strip()}")
                bad += 1

        code, out = run_check()
        ok = code == 0
        print("  [OK] 还原后红线全绿" if ok else "  [MISS] 还原后红线没恢复")
        if not ok:
            print(out[-600:])
            bad += 1
    finally:
        unlock_reverse_verify()
        dirty = [str(p.relative_to(ROOT)) for p, h in before.items() if sha(p) != h]
        if dirty:
            print(f"⚠️ 逐字节还原自检失败：{dirty} —— 尝试按快照还原")
            restore_snapshot(snapshot_dir())
            bad += 1
        else:
            print(f"✅ 逐字节还原自检：{len(before)}/{len(touched)} 个注入点文件与跑之前完全一致")

    print()
    if bad:
        print(f"❌ {bad} 条不成立（红线对它们不敏感，或者现场没还干净）")
        return 1
    print(f"✅ 全部 {len(MUTATIONS)} 种注入都被抓到 + 源码已还原（sha256 一致）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
