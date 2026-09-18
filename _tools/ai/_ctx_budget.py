"""算清「我们的压缩到底什么时候才会触发」——把"感觉没做好"换成数字。

只做算术，不连网、不读真机：常数全部来自 `android/.../ai/AiContext.kt`（改那份文件后请同步这里）。

要看的三件事：
  1. 压缩（COMPACT_AT=40%）与硬裁（HARD_LIMIT=90%）分别在多少 token 触发；
  2. 折算成"多少轮对话"——用真机实测的单条消息体量（见下）换算；
  3. 与业界标准做法（滑动窗口 N 轮 + 滚动摘要）对比：同样一段对话，两边各发多少。

实测输入（2026-09-17 从模拟器 ai_conversations_u1.json 拉下来算的）：
  · 会话 01629d95：10 条消息 → 正文约 1,168 token（含带表格那几轮）
  · 会话 23c0971e：4 条消息 → 正文约 736 token
即"一条消息"平均约 100~190 token；但助手答案带表格时单条可达上千。
"""
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

# ---- 与 AiContext.kt 对齐的常数（改了那边记得改这里）----
COMPACT_AT = 0.40          # 用到窗口这个比例就压缩
HARD_LIMIT = 0.90          # 送出去的请求无论如何不超过窗口这个比例
KEEP_RECENT_MESSAGES = 6   # 压缩时保留多少条最近消息
WINDOWS = [("deepseek-flash（实测推断）", 1_048_576), ("认不出模型时的兜底", 128_000), ("收缩地板", 32_000)]

# 三种对话形态：每条消息平均多少 token（一次问答 = 2 条消息）
PROFILES = [
    ("轻问答（问一句答一句）", 150),
    ("带表格的报表问答", 450),
    ("长表格 + 长明细", 1_500),
]


def main() -> int:
    print("一、两道闸分别在多少 token 触发\n")
    print(f"{'窗口':<28}{'窗口':>12}{'压缩触发(40%)':>16}{'硬裁触发(90%)':>16}")
    for name, w in WINDOWS:
        print(f"{name:<28}{w:>12,}{int(w * COMPACT_AT):>16,}{int(w * HARD_LIMIT):>16,}")
    print()

    print("二、折算成「多少条消息 / 多少轮问答」才会触发压缩\n")
    print(f"{'对话形态':<26}{'每条消息':>10}{'触发压缩的消息数':>18}{'折合轮问答':>12}")
    for name, per_msg in PROFILES:
        for wname, w in WINDOWS[:1]:  # 只看 deepseek-flash
            n = int(w * COMPACT_AT) // per_msg
            print(f"{name:<26}{per_msg:>10}{n:>18,}{n // 2:>12,}")
    print()

    print("三、同一段对话，两种策略各发多少（按「带表格的报表问答」450 token/条）\n")
    per_msg = 450
    print(f"{'轮次':>6}{'消息数':>8}{'我们当前策略':>16}{'固定预算(6轮+摘要)':>20}")
    for turns in (1, 5, 10, 20, 50, 100, 500):
        msgs = turns * 2
        ours = msgs * per_msg                       # 压缩没触发前：整段对话全发
        theirs = 6 * per_msg + 400                  # 最近 6 条原文 + 一段约 400 token 的滚动摘要
        print(f"{turns:>6}{msgs:>8}{ours:>16,}{theirs:>20,}")
    print()
    print("注：我们当前策略在压缩**触发之前**就是「整段全发」——上面第 1 列的算法就是它。")
    print("    deepseek-flash 下要")
    print(f"    触发压缩需要 {int(WINDOWS[0][1] * COMPACT_AT):,} token ≈ "
          f"{int(WINDOWS[0][1] * COMPACT_AT) // per_msg // 2:,} 轮问答。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
