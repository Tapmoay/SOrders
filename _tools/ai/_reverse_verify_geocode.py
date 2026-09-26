"""反向验证 §18（地址类动作必须把地址换成坐标）。

## 为什么每个红线都要有这么一个脚本
判据写完的那一刻是绿的，**不代表它会红**。一条永远绿的检查比没有检查更糟：
它给人一种"这件事有人守着"的错觉。所以每条红线都要证明一次"把 bug 注入进去，
它真的会报错"——通常是临时改坏源码 → 跑检查 → 断言它是红的 → 立刻还原。

本脚本对 §18 的四条判据各注入一次：
  1. 删掉一个动作的 `geocodeFrom` → 判据①必须红
  2. 从 `ADDRESS_KEYS` 里拿掉 `GEO_LAT` → 判据②必须红（这是真机上出现过的"悄悄丢掉"）
  3. 去掉 `geocodeRequired = true` → 判据③必须红
  4. 删掉 `geoNote` → 判据④必须红
另加一条"完好时必须是绿的"，否则前面四条红了也说明不了问题（可能本来就红）。

用法：`python _reverse_verify_geocode.py`
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# Windows 控制台默认是 GBK：不重设的话，打印 ✅/§ 这类字符会 UnicodeEncodeError，
# 于是脚本"因为打印而失败"，看起来像判据坏了。
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
BASIC = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteBasicData.kt"
CRUD = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteCrudHandlers.kt"

# 每条 = (说明, 要改的文件, 改法)。改法直接对源码做字符串替换，跑完立刻还原。
CASES: list[tuple[str, Path, object]] = [
    (
        "删掉一个 geocodeFrom（地址不再换坐标）",
        BASIC,
        lambda s: s.replace('            geocodeFrom = "detail_address",\n', "", 1),
    ),
    (
        "把 GEO_LAT 从 ADDRESS_KEYS 里拿掉（坐标被 pick 悄悄丢掉）",
        BASIC,
        lambda s: s.replace(
            '"receiver_name", "phone", "detail_address", "origin_address", "remark", GEO_LAT, GEO_LNG,',
            '"receiver_name", "phone", "detail_address", "origin_address", "remark", GEO_LNG,',
            1,
        ),
    ),
    (
        "去掉 geocodeRequired（改了地址却定位不到时不再拒绝）",
        BASIC,
        lambda s: s.replace("            geocodeRequired = true,\n", "", 1),
    ),
    (
        "删掉 geoNote（定位失败的后果不再写在卡上）",
        CRUD,
        lambda s: s.replace("private fun geoNote(", "private fun geoNoteREMOVED(", 1),
    ),
]


def run_check() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(HERE / "_check_ai_guardrails.py")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    fails: list[str] = []

    # 0. 完好时必须绿（不然下面"变红"没有意义）
    code, out = run_check()
    if code != 0:
        # §18 这一节自己报的错才有意义；别的节红不属于本脚本的范围
        sec18 = "== 18." in out and "❌" in out.split("== 18.")[-1]
        fails.append(f"前提不成立：源码完好时检查就没过（§18 红的={sec18}）\n{out[-1500:]}")
        print("\n".join(fails))
        return 1
    print("✅ 前提：源码完好时检查是绿的")

    for label, path, mutate in CASES:
        original = path.read_text(encoding="utf-8")
        mutated = mutate(original)
        if mutated == original:
            fails.append(f"{label}：注入没生效（源码里那段已经变了，请更新本脚本的替换串）")
            continue
        try:
            path.write_text(mutated, encoding="utf-8", newline="")
            code, out = run_check()
        finally:
            path.write_text(original, encoding="utf-8", newline="")
        # R3-07b：还原**当场核对**（不是「看起来还原了」）—— 对不上就记账，别让坏代码留在树里
        if path.read_text(encoding="utf-8") != original:
            fails.append(f"{label}：还原后与快照不一致 —— 注入污染了源码树")
            continue
        sec18 = out.split("== 18.")[-1] if "== 18." in out else ""
        if code == 0 or "❌" not in sec18:
            fails.append(f"{label}：注入后 §18 没有报红（code={code}）——判据是空转的")
        else:
            print(f"✅ 注入「{label}」→ §18 报红")

    if fails:
        print("\n❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print("\n✅ §18 的四条判据都证明会红。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
