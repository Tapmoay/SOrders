"""反向验证：**fuzz 工具自己的安全轨与自检**是不是真的在起作用。

## 为什么工具也要反向验证
这一轮（2026-09-18）差点栽在工具自己身上：契约模糊测试把 `1e20` 喂给
`POST /price-rules/batch`，该端点没有上限校验，**一次把 2880 条专属价全改了**
（其中 2822 条是凭空新建的，后来靠 09-15 的库备份 + operation_logs 的 before 值才还原）。

事后加了三道轨：
1. `_fuzzlib.BULK_PATTERN`：批量/全量端点**按类**禁止（不是只拉黑出事的那一个）；
2. `_fuzzlib.denied()` + 工具里的二次确认：发请求前先过白名单；
3. 工具自检（`Report.guard`）：看不见目标 / 安全模式没生效时**直接非零退出**，
   而不是"自检失败但照样给结论"。

这三道轨如果不能被证明"坏了就会红"，那它们和没写一样——所以这里按项目惯例做反向注入：
改坏一处 → 跑工具 → 断言它**确实**以失败告终且提示对得上。

用法：`python _tools/fuzz/_reverse_verify_fuzz_safety.py`
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

HERE = Path(__file__).resolve().parent
LIB = HERE / "_fuzzlib.py"
CONTRACT = HERE / "_fuzz_contract.py"
#: 不变式审计工具（④ 测的是它里面"扫了 0 行"的分辨判据）
INV = HERE / "_fuzz_invariants.py"


def run(script: Path, *args: str, timeout: int = 180) -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    fails: list[str] = []

    # ---- 前提：源码完好时，工具自己会拦批量端点、且自检通过
    code, out = run(HERE / "_list_ops.py", "--danger")
    if "price-rules/batch" not in out:
        print("❌ 前提不成立：完好状态下 _list_ops 没把 /price-rules/batch 列为禁止")
        return 1
    print("✅ 前提：完好状态下批量调价在禁止清单里（按类拦，不是点名拦）")

    # ---- ① 拆掉「批量/全量端点按类禁止」这条轨：工具应当**自检失败**（退出码 3）
    original = LIB.read_text(encoding="utf-8")
    mutated = original.replace(
        "    if BULK_PATTERN.search(p):\n        return BULK_WHY\n", "", 1
    )
    if mutated == original:
        fails.append("① 注入没生效（_fuzzlib.py 里的 BULK_PATTERN 分支找不到了，请更新本脚本）")
    else:
        try:
            LIB.write_text(mutated, encoding="utf-8", newline="")
            code, out = run(CONTRACT, "--only", "/products", "--max", "20")
        finally:
            LIB.write_text(original, encoding="utf-8", newline="")
        if code != 3 or "批量调价" not in out:
            fails.append(f"① 拆掉批量端点白名单后，契约测试没有自检失败（code={code}）"
                         f"——说明那条轨是空转的")
        else:
            print("✅ 注入「拆掉批量端点白名单」→ 工具自检失败并指名 /price-rules/batch")

    # ---- ② 让"路径参数一律用不存在的 id"失效：自检必须发现
    original = LIB.read_text(encoding="utf-8")
    mutated = original.replace(
        '    return re.sub(r"\\{([^}]+)\\}", sub, path)',
        '    return path',
        1,
    )
    if mutated == original:
        fails.append("② 注入没生效（fill_path 的实现变了，请更新本脚本）")
    else:
        try:
            LIB.write_text(mutated, encoding="utf-8", newline="")
            code, out = run(CONTRACT, "--only", "/products", "--max", "20")
        finally:
            LIB.write_text(original, encoding="utf-8", newline="")
        if code != 3 or "安全模式" not in out:
            fails.append(f"② 安全模式失效后没有被自检拦住（code={code}）"
                         f"——真跑起来会拿真实 id 去改业务数据")
        else:
            print("✅ 注入「路径参数不再替换成假 id」→ 自检失败（否则真的会动业务数据）")

    # ---- ③ 把 guard 改成不退出：空转的运行就会"看起来通过"
    #    ⚠️ `sys.exit(3)` 在 **_fuzzlib.py** 的 `Report.guard` 里（第一版写成了去
    #    `_fuzz_contract.py` 里找，结果"注入没生效"——反向验证脚本自己先错了）
    original_g = LIB.read_text(encoding="utf-8")
    mutated_g = original_g.replace(
        '        sys.exit(3)',
        '        return  # 注入：不再中止',
        1,
    )
    if mutated_g == original_g:
        fails.append("③ 注入没生效（_fuzzlib.py 里找不到 sys.exit(3)）")
    else:
        try:
            LIB.write_text(mutated_g, encoding="utf-8", newline="")
            # 只有几个端点 + 极小预算：正常会因自检失败中止（3），现在应当"顺利跑完"
            code, out = run(CONTRACT, "--only", "/products", "--max", "3")
        finally:
            LIB.write_text(original_g, encoding="utf-8", newline="")
        if code == 3:
            fails.append("③ guard 被改成不退出后，工具仍然以 3 退出——那条自检可能来自别处")
        else:
            print(f"✅ 注入「guard 不再中止」→ 空转的运行不再被拦住（code={code}），"
                  f"证明自检就是那道闸")

    # ---- ④ 「扫了 0 行」的分辨判据不许被改松（2026-09-21 加的那条）
    #    那条判据把 0 行分成两种：能证明"本机没有这类数据" → 信息；否则 → 可疑。
    #    ⚠️ 这里**直接测它的契约**，不用注入：注入口只能选在"本机真实存在"的判据上，
    #       而本机的 5 条空转判据全都是"数据确实没有"那一类 —— 没有一条能用来证明"该可疑"。
    sys.path.insert(0, str(HERE))
    import _fuzz_invariants as FI  # noqa: E402

    code, out = run(INV, "--check")
    if code != 0 or "这次没东西可查" not in out or "可疑 0" not in out:
        fails.append(f"④ 前提不成立：完好状态下 _fuzz_invariants 没把空转判据说明白（code={code}）")
    else:
        print("✅ 前提：完好状态下空转的判据被说明成「本机没有这类数据」，可疑 0")

    # 方向一：字面量**命中库里真实取值**（`bill_type='piece'` 本机 267 行都是）→ 不许放行。
    #        这正是当年"5 条判据写成小写、库里是大写"那个坑的形状。
    if FI._idle_reason("select count(*) from driver_bills where bill_type='piece'") is not None:
        fails.append("④ 判据放行了一条『字面量在库里确实存在』的 SQL —— 小写/大写那个坑会复活")
    else:
        print("✅ 方向一：字面量命中库里真实取值 → 不放行（上层仍然报「可疑」）")
    # 方向二：字面量库里根本不存在（`salary`）→ 说明"本机没有这类数据"，并把真实取值打出来
    why = FI._idle_reason("select count(*) from driver_bills where bill_type='salary'")
    if not why or "piece" not in why:
        fails.append(f"④ 判据没能说明『本机没有这类数据』或没打出真实取值（返回 {why!r}）")
    else:
        print("✅ 方向二：字面量库里不存在 → 说明原因并打出真实取值（人一眼能看出是没数据还是写错）")
    # 方向三：认不出的 SQL 形状 → 必须不放行（fail-closed，宁可吵也不许静默放行）
    if FI._idle_reason("select count(*) from (select 1 from nope where y='z')") is not None:
        fails.append("④ 认不出的 SQL 形状被放行了 —— 分辨不出时必须按「可疑」报")
    else:
        print("✅ 方向三：认不出的形状 → 不放行（fail-closed）")

    if fails:
        print("\n❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print("\n✅ fuzz 工具的四道轨（批量端点白名单 / 安全模式自检 / guard 中止 / "
          "「扫了 0 行」的分辨判据）全部证明是活的。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
