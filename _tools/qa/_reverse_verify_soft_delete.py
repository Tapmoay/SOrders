"""反向验证「软删的行不许还能被改」这条红线**真的会红**（R11-F4）。

## 为什么这条必须反向验证
这条判据的形状很讨巧：它靠**源码文本**判断"这个端点想没想过 is_deleted"，
所以它有一大类"看起来在查、其实什么都没查"的失效方式：
- 锚点写错（第一版把尾段写成 `\\w+$`，于是 `set-default` **整个被跳过**——而它恰好就是漏的那个洞）；
- 太松（第一版只要求"函数体里出现过软删模型"，于是把 `PATCH /order-products/{line_id}`
  报成缺陷——它只是查一下参考商品来抄成本快照，`_check_product_ref()` 里已经拦了软删）；
- 太紧（把 restore 端点也算进来 → 永远红 → 没人看）。

所以这里逐条注入，证明它**会红**，并且**每一处注入都能被后端测试也抓住**
（测试与红线两条腿：红线管"清单完整"，测试管"行为真的是 400 且数据没变"）。

用法：python _tools/qa/_reverse_verify_soft_delete.py        # 全部达标 → 退出码 0
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_soft_delete_guards.py"
PYTEST_TARGET = "tests/test_soft_deleted_row_not_updatable.py"
API = ROOT / "backend/app/api/v1"
MODELS = ROOT / "backend/app/models"

# (说明, 相对路径, 注入函数, 期望红的方式)
#   期望红的方式："check" = 红线必须报红；"check+pytest" = 红线与后端测试都要报红
CASES: list[tuple[str, str, object, str]] = [
    (
        "运费模板的守卫被拿掉（改一条看不见的模板照样 200）",
        "backend/app/api/v1/freight_templates.py",
        lambda s: re.sub(r"\n\s*ensure_alive\(t, \"运费模板\"[^\n]*\n", "\n", s, count=1),
        "check+pytest",
    ),
    (
        "挂账单位的守卫被拿掉",
        "backend/app/api/v1/arrears.py",
        lambda s: re.sub(r"\n\s*ensure_alive\(u, \"挂账单位\"[^\n]*\n", "\n", s, count=1),
        "check+pytest",
    ),
    (
        "专属价的守卫被拿掉（改一条看不见的价、还写一条假调价日志）",
        "backend/app/api/v1/price_rules.py",
        lambda s: re.sub(r"\n\s*ensure_alive\(pr, \"批发商专属价\"[^\n]*\n", "\n", s, count=1),
        "check+pytest",
    ),
    (
        "默认地址的守卫被拿掉（默认标记落在看不见的行上）",
        "backend/app/api/v1/shipper.py",
        lambda s: re.sub(r"\n\s*ensure_alive\(a, \"地址\"[^\n]*\n", "\n", s, count=1),
        "check+pytest",
    ),
    (
        "判据自己空转：把三个模型的混合式软删声明全删掉（扫到的模型 < 下限）",
        "backend/app/models/shipper.py",
        # ⚠️ 2026-09-21 更新：这里原来还跟着一句 `.replace("    is_deleted:", "    isDeletedX:")`，
        #    它是**空转** —— `models/shipper.py` 里根本没有那一行（那三个模型是
        #    `SoftDeleteMixin` **混入式**声明，`is_deleted` 只写在 `base.py` 的 mixin 里）。
        #    注入里留一句永远不生效的替换，会让人以为"那一路也验过了"，所以删掉；
        #    真正让判据空转的是前一句（把混入的名字改掉）。
        lambda s: s.replace("SoftDeleteMixin", "XSoftDelete"),
        "check",
    ),
]


def run_check() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def run_pytest() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, "-m", "pytest", PYTEST_TARGET, "-q", "--no-header", "-p", "no:cacheprovider"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ROOT / "backend"),
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    fails: list[str] = []

    code, out = run_check()
    if code != 0:
        print("❌ 前提不成立：源码完好时红线就没过")
        print(out[-1200:])
        return 1
    code, out = run_pytest()
    if code != 0:
        print("❌ 前提不成立：源码完好时后端测试就没过")
        print(out[-1200:])
        return 1
    print("✅ 前提：源码完好时，红线与后端测试都是绿的")

    for label, rel, mutate, expect in CASES:
        path = ROOT / rel
        original = path.read_text(encoding="utf-8")
        mutated = mutate(original)
        if mutated == original:
            fails.append(f"{label}：注入没生效（锚点变了，请更新本脚本）")
            continue
        try:
            path.write_text(mutated, encoding="utf-8", newline="")
            c_code, c_out = run_check()
            t_code, t_out = ("", "") if expect == "check" else run_pytest()
        finally:
            path.write_text(original, encoding="utf-8", newline="")
        # R3-07b：还原**当场核对**（不是「看起来还原了」）—— 对不上就记账，别让坏代码留在树里
        if path.read_text(encoding="utf-8") != original:
            fails.append("还原后与快照不一致（注入污染了源码树）：" + str(path))

        red_check = c_code != 0
        red_test = t_code != 0 if expect == "check+pytest" else True
        ok = red_check and red_test
        if ok:
            which = "红线" + ("+后端测试" if expect == "check+pytest" else "")
            print(f"✅ 注入「{label}」→ {which} 报红")
        else:
            fails.append(
                f"{label}：注入后 {'红线' if red_check else '红线没红'}"
                f"{'、后端测试也红了' if red_test else '、后端测试没红'}（红线码={c_code} 测试码={t_code}）"
            )
            for ln in (c_out or "").splitlines()[-6:]:
                print("     [check] " + ln.strip())

    print()
    if fails:
        print("❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"✅ {len(CASES)} 条注入都证明这条红线真的在检查。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
