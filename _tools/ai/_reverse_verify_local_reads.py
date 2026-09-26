"""反向验证「本机能力（读手机定位）」那一组判据**真的会红**（注入 bug → 必须报错）。

## 为什么每个红线都要有这么一个脚本
判据写完的那一刻是绿的，**不代表它会红**。一条永远绿的检查比没有检查更糟：
它给人一种"这件事有人守着"的错觉。本脚本对 `_check_ai_guardrails.py` 的
"== 2b-3. 本机能力（读手机定位）==" 那一节逐条注入，每次都必须让**那一条**报红。

## 十一种破坏方式（每一种都对应一个真实后果，不是形式主义）
  ① 本机读能力的输出里塞坐标 → **坐标泄漏进模型上下文**（本仓第一条硬规矩）
  ② 执行侧不再认「path 为空」 → 去发一个不存在的请求（本机能力当场全废）
  ③ 模块白名单退回"只有后端目录" → `location` 这个开关**根本不存在**，本机能力被静默过滤
  ④ 设置页只列后端模块 → 用户关不掉定位（隐私）
  ⑤ 生产实现不走 `AiLocation.resolveAddress` → 句柄落到地理编码那条路（**漂点**）
  ⑥ 句柄写进地址栏的是模型给的原文 → 地址库里是**四个字**「当前位置」，司机导航到那儿
  ⑦ 机器生成的目录里混进本机能力 → 生成器一跑就抹掉；`_probe_read_roles.py` 还会拿空路径打后端
  ⑧ 白名单不再认"保存之后新出现的模块" → **老用户更新完还是读不到定位**（用户拍板不许这样）
  ⑨ 空集白名单也被补新模块 → 把用户主动"全关"的又打开（这次关的是隐私）
  ⑩ **工具开关的读路径又去写盘** → 新加的工具只有第一次读是开的，之后自己变回关的
     （2026-09-21 修的静默丢能力；用户原话：「ai 它是要具备**所有功能**」）
  ⑪ 合并规则被搬回 `enabledTools()` 自己算 → 那处纯函数没人调，单测再也钉不住"只读"

用法：`python _tools/ai/_reverse_verify_local_reads.py`   # 11/11 都红 → 退出码 0
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Windows 控制台默认是 GBK：不重设的话，打印 ✅/§ 这类字符会 UnicodeEncodeError，
# 于是脚本"因为打印而失败"，看起来像判据坏了。
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
AI = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai"
CHECK = HERE / "_check_ai_guardrails.py"

LOCAL = AI / "AiLocalReads.kt"
SVC = AI / "AiReadService.kt"
READS = AI / "AiReads.kt"
KEYSTORE = AI / "AiKeyStore.kt"
WSVC = AI / "AiWriteDataSource.kt"
WORDER = AI / "AiWriteOrderHandlers.kt"
CATALOG = AI / "AiReadCatalog.kt"

# 每条 = (说明, 文件, 原文, 替换成, 期望报红的判据名)
MUTATIONS: list[tuple[str, Path, str, str, str]] = [
    (
        "本机读能力的输出里塞进坐标（坐标泄漏进模型上下文）",
        LOCAL,
        '            put("address", place.address)',
        '            put("address", place.address)\n            put("lat", place.lat)',
        "本机读能力那一份里不许出现经纬度",
    ),
    (
        "执行侧不再认「path 为空」（去发一个不存在的请求）",
        SVC,
        "        if (action.path.isBlank()) return AiLocalReads.run(action, locationProvider())",
        "        if (false) return AiLocalReads.run(action, locationProvider())",
        "执行侧认「path 为空」走本机分支",
    ),
    (
        "模块白名单退回「只有后端目录」（location 这个开关根本不存在）",
        KEYSTORE,
        "        val all = AiReads.allModules().toSet()",
        "        val all = AiReadCatalog.modules().toSet()",
        "模块白名单含本机模块",
    ),
    (
        "设置页只列后端模块（定位那一行开关消失）",
        AI.parent / "ui" / "ai" / "AiSettingsViewModel.kt",
        "AiReads.allModules().filter { it in mine }",
        "AiReadCatalog.modules().filter { it in mine }",
        "设置页按同一份模块清单列开关",
    ),
    (
        "生产实现绕开 AiLocation.resolveAddress（句柄落到地理编码，会漂点）",
        WSVC,
        "        AiLocation.resolveAddress(text, locationProvider(), geocode = { geocode(it) })",
        "        geocode(text)?.let { AiPlace(address = text, lat = it.first, lng = it.second) }",
        "生产实现把定位提供者接进去",
    ),
    (
        "订单把模型给的原文写进地址栏（库里变成「当前位置」四个字）",
        WORDER,
        '                put("address_detail", addressText)',
        '                put("address_detail", address)',
        "订单 create 写的是解析后的地址",
    ),
    (
        "机器生成的目录里混进本机能力（生成器一跑就抹掉）",
        CATALOG,
        "    val ACTIONS: List<ReadAction> = listOf(",
        '    val ACTIONS: List<ReadAction> = listOf(\n        ReadAction("location.current", "本机", "", "", setOf("shipper"), false, emptyList()),',
        "机器生成的目录里不许出现本机能力",
    ),
    (
        # 用户拍板：「这个权限给它开啊」= 更新完就该能用。去掉标记逻辑之后，
        # 老用户那份白名单（存的时候还没有 location）就永远补不上它 —— 静默、不报错。
        "白名单不再认「保存之后新出现的模块」（老用户更新完还是读不到定位）",
        READS,
        "        val appeared = knownAtSave?.let { all - it } ?: AiLocalReads.MODULES.toSet()",
        "        val appeared = AiLocalReads.MODULES.toSet()",
        "『保存之后新出现的模块』由标记算出来",
    ),
    (
        # 反过来的那一半：把「空集 = 全关」的老约定也当成枚举去补 —— 等于把用户明确关掉的
        # 东西又打开，而这次关的是隐私。
        "空集白名单也被补上新模块（把用户主动「全关」的又打开）",
        READS,
        "        if (saved.isEmpty()) return emptySet()",
        "        if (false) return emptySet()",
        "空集按老约定当『全关』",
    ),
    (
        # 2026-09-21 修的那个 bug 的**根因**：读的时候顺手写盘，把"见过的清单"刷成当前全集
        # → 新加的工具只有第一次读是开的，之后自己变回关的（用户原话：AI 要具备**所有功能**）。
        "工具开关的读路径又去写盘（新加的工具会自己变回关的）",
        KEYSTORE,
        "            return defaultEnabledTools(role)",
        "            prefs.edit().putString(KEY_TOOLS_SEEN, DEFAULT_ENABLED_TOOLS.joinToString(\",\")).apply()\n"
        "            return defaultEnabledTools(role)",
        "工具开关的读路径不许写盘",
    ),
    (
        # 同一件事的另一半：合并规则被搬回 `enabledTools()` 自己算 —— 那处纯函数就**没人调**了，
        # 单测再也钉不住它，"只读"这条保证随之消失（这正是这个 bug 当年长出来的方式）。
        "合并规则被搬回 enabledTools 自己算（纯函数没人调了）",
        KEYSTORE,
        "        return resolveEnabledTools(",
        "        return toolsWhitelistInline(",
        "读侧走那条纯函数",
    ),
]


def run_check() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(CHECK)],
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
        sec = "== 2b-3." in out and "❌" in out.split("== 2b-3.")[-1]
        fails.append(f"前提不成立：源码完好时检查就没过（本机能力那节红的={sec}）\n{out[-1500:]}")
        print("\n".join(fails))
        return 1
    print("✅ 前提：源码完好时检查是绿的")

    for label, path, old, new, expect in MUTATIONS:
        original_bytes = path.read_bytes()
        original = original_bytes.decode("utf-8").replace(chr(13) + chr(10), chr(10))
        if original.count(old) != 1:
            fails.append(f"{label}：注入没生效（原文出现 {original.count(old)} 次，请更新本脚本的替换串）")
            continue
        try:
            path.write_text(original.replace(old, new), encoding="utf-8", newline="")
            code, out = run_check()
        finally:
            path.write_bytes(original_bytes)
        # R3-07b：还原**当场核对**（不是「看起来还原了」）—— 对不上就记账，别让坏代码留在树里
        if path.read_bytes() != original_bytes:
            fails.append("还原后与快照不一致（注入污染了源码树）：" + str(path))
        sec = out.split("== 2b-3.")[-1] if "== 2b-3." in out else ""
        hit = any("[FAIL]" in ln and expect in ln for ln in out.splitlines())
        if hit:
            print(f"✅ 注入「{label}」→ 判据报红")
        else:
            fails.append(f"{label}：注入后「{expect}」没有报红（code={code}）——判据是空转的\n{sec[-600:]}")

    if fails:
        print("\n❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"\n✅ 本机能力那 {len(MUTATIONS)} 条判据都证明会红。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
