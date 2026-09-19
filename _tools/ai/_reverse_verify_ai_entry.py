"""反向验证 `_check_ai_guardrails.py` 里「AI 入口落位」那几条检查**真的会红**。

### 为什么要单独写这个脚本
本次会话已经抓到 **3 条"永远通过"的检查**（模式写错、断言作用域太宽、名字对不上），
它们的共同点是：**跑起来是绿的，但其实什么都没检查**。绿色的检查比没有检查更危险——
没有检查时你会去读代码拿一手真相，有假检查时你会相信绿灯直接动手。

所以每条新检查都要走一遍这个循环：**注入那个 bug → 跑 → 确认它红在预期的那一条 → 还原**。
这里把"入口落位"的 6 种破坏方式固化成脚本，以后重跑即可（幂等：改完一定还原）。

用法：python _tools/ai/_reverse_verify_ai_entry.py     # 6/6 都红 → 退出码 0
"""
import shutil
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402

ROOT = repo_root()
MOD = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/nav/Modules.kt"
HOME = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/home/RoleHomeScreen.kt"
CHAT = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/ai/AiChatScreen.kt"
BRAND = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/theme/AiBrand.kt"
CHECK = Path(__file__).resolve().parent / "_check_ai_guardrails.py"

AI_ENTRY = 'ModuleEntry("AI 助手", Routes.AI_CHAT, Icons.Default.AutoAwesome, color = AiBlue),'

# 货主端那个入口现在是多行具名参数（带渐变），整块删掉要用多行原文。
AI_ENTRY_SHIPPER = (
    "        ModuleEntry(\n"
    '            label = "AI 助手",\n'
    "            route = Routes.AI_CHAT,\n"
    "            icon = Icons.Default.AutoAwesome,\n"
    "            color = AiBlue,\n"
    "            gradient = listOf(AiBlue, AiPurple, AiPink), // Google AI 三段品牌渐变\n"
    "        ),\n"
)

# (说明, 目标文件, 被替换的原文, 替换成, 期望变红的那条检查名（子串）)
MUTATIONS = [
    (
        "货主端删掉 AI 入口（货主就没 AI 可用了）",
        MOD,
        AI_ENTRY_SHIPPER,
        "",
        "货主端 AI 入口 = 工作台网格里的图标",
    ),
    (
        "货主端 AI 图标退化成单色（丢掉 Google 品牌渐变）",
        MOD,
        "gradient = listOf(AiBlue, AiPurple, AiPink), // Google AI 三段品牌渐变",
        "",
        "货主工作台那块 AI 图标用渐变",
    ),
    (
        "品牌渐变的颜色顺序写反（蓝紫粉被打乱，观感就不对了）",
        BRAND,
        "val AiBrandColors: List<Color> = listOf(Color(AiBlue), Color(AiPurple), Color(AiPink))",
        "val AiBrandColors: List<Color> = listOf(Color(AiPink), Color(AiPurple), Color(AiBlue))",
        "渐变只有一处定义，顺序写死",
    ),
    (
        "货主端放两个 AI 入口（用户会以为是两个功能）",
        MOD,
        'ModuleEntry("我的订单", Routes.SHIPPER_ORDERS, Icons.Default.ListAlt, color = ProgressYellow),',
        'ModuleEntry("我的订单", Routes.SHIPPER_ORDERS, Icons.Default.ListAlt, color = ProgressYellow),\n'
        '        ModuleEntry("AI 助手副本", Routes.AI_CHAT, Icons.Default.AutoAwesome, color = AiBlue),',
        "货主工作台里 AI **恰好一个**入口",
    ),
    (
        "司机端也加 AI 入口（司机不开放）",
        MOD,
        'ModuleEntry("我的任务", Routes.DRIVER_ORDERS, Icons.Default.LocalShipping, color = MgrGreen),',
        'ModuleEntry("我的任务", Routes.DRIVER_ORDERS, Icons.Default.LocalShipping, color = MgrGreen),\n'
        "        " + AI_ENTRY,
        "司机端工作台没有 AI 入口",
    ),
    (
        "派单端网格里重复放 AI（圆钮 + 网格两个入口）",
        MOD,
        'ModuleEntry("消息中心", Routes.MESSAGES, Icons.Default.Notifications, color = MessageRed),\n'
        "        // ⚠️ AI 助手",
        "        " + AI_ENTRY + "\n"
        '        ModuleEntry("消息中心", Routes.MESSAGES, Icons.Default.Notifications, color = MessageRed),\n'
        "        // ⚠️ AI 助手",
        "派单端网格里不重复放 AI",
    ),
    (
        "圆钮改回给所有非司机角色（3 Tab 端又会落在 1/4 处）",
        HOME,
        "val showAiButton = role == Role.DISPATCHER",
        "val showAiButton = role != Role.DRIVER",
        "派单端圆钮只给派单员",
    ),
    (
        "输入框提示语写死成派单员的例子（货主照着敲只会撞权限墙）",
        CHAT,
        # v3.32：读文件时提示语要让位给「正在读文件…」，所以注入点跟着变成那一行原文。
        'placeholder = { Text(if (attaching) "正在读文件…" else hint, fontSize = 15.sp) },',
        'placeholder = { Text("例如：哪些商品库存到红线了？", fontSize = 15.sp) },',
        "输入框里不许再把派单员的例子写死",
    ),
    (
        "货主端提示语举例「库存」（货主没有这个能力）",
        CHAT,
        'private const val HINT_SHIPPER = "例如：帮我加一个常用地址"',
        'private const val HINT_SHIPPER = "例如：哪些商品库存到红线了？"',
        "货主端的提示语不许举例货主没有的能力",
    ),
]


def read_src(path: Path) -> tuple[str, bool]:
    """读源码 + 记住它原本是不是 CRLF。

    ⚠️ 踩坑（本脚本第一版就犯）：`Path.read_text()` 会把 CRLF **统一成 \\n**，
    再 `write_text(newline="")` 写回去，整个文件的行尾就被压成 LF 了。
    对于 git 跟踪的文件（RoleHomeScreen.kt / Modules.kt），那等于**整个文件 100+ 行
    的假 diff**——真正的改动只有十几行，review 时根本看不出改了什么。
    所以一律按字节读、按字节写，只改中间那一小段。
    """
    data = path.read_bytes()
    # 注意：这里**不用** read_text()，它对 CRLF 做统一换行；也不留 CRLF——
    # 统一成 \n 才能让下面的多行 old/new 字面量写得干净，写回时再由 write_src 还原。
    return data.decode("utf-8").replace("\r\n", "\n"), b"\r\n" in data


def write_src(path: Path, text: str, crlf: bool) -> None:
    data = text.replace("\r\n", "\n")
    if crlf:
        data = data.replace("\n", "\r\n")
    path.write_bytes(data.encode("utf-8"))


def run_check() -> str:
    r = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return (r.stdout or "") + (r.stderr or "")


def main() -> int:
    bad = 0
    for label, path, old, new, expect in MUTATIONS:
        src, crlf = read_src(path)
        if src.count(old) != 1:
            print(f"  [SKIP] {label} —— 原文出现 {src.count(old)} 次，无法唯一替换")
            bad += 1
            continue
        write_src(path, src.replace(old, new), crlf)
        try:
            out = run_check()
        finally:
            write_src(path, src, crlf)
        fails = [ln for ln in out.splitlines() if "[FAIL]" in ln]
        hit = any(expect in ln for ln in fails)
        print(f"  [{'OK' if hit else 'MISS'}] {label} → 期望红：{expect}（实际红 {len(fails)} 条）")
        if not hit:
            for ln in fails:
                print("        " + ln.strip())
            bad += 1
    print(
        "\n"
        + (
            f"✅ {len(MUTATIONS)}/{len(MUTATIONS)} 都红了：这些检查真的在检查。"
            if bad == 0
            else f"❌ {bad}/{len(MUTATIONS)} 条没红：检查是假的，必须改。"
        )
    )
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
