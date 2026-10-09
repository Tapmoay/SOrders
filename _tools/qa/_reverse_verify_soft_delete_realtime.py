"""反向验证「软删/恢复要发实时信号、司机端不许静默、详情页要说人话」这条红线**真的会红**（BUG-0027 / 测试台账 TA-05 + TA-06）。

## 为什么这条必须反向验证
这一单的判据（`_tools/qa/_check_soft_delete_realtime.py`，60 条）横跨**四个后端文件 + 五个安卓文件**，
而且有一大半是"锚点式"的（"这个分支真的调了那个函数"、"这两句文案逐字相等"）。锚点式判据有三大类
失效方式，光看它绿是看不出来的：

- **锚点失效**：函数改名、分支被掏空、代码挪进注释 —— 判据扫不到就悄悄放行（本项目已经栽过一次：
  注释满足了判据）；
- **太松**：只要求"出现过 order.deleted 这个词"，于是站内信有、实时信号没有（**那正是 TA-05 的病根**）
  也照样绿；
- **跨语言对账写反了**：安卓的 HINTS 与后端的 DELETED_ORDER_NOTICES 少一句、改一个字，靠人眼看是看不出来的。

所以这里逐条注入，证明**每一处注入都能让判据报红**；其中动了后端行为的几条，要求**测试也一起红**
（红线管"接线还在不在"，测试管"行为真的是那样"）。

用法：python _tools/qa/_reverse_verify_soft_delete_realtime.py     # 全部达标 → 退出码 0
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_soft_delete_realtime.py"
PYTEST_TARGET = "tests/test_soft_delete_realtime.py"
SAFETY = ROOT / "_tmp/test_round3/_rv_SoftDeleteRealtime_safety"

LIFECYCLE = "backend/app/api/v1/orders_lifecycle.py"
COMMON = "backend/app/api/v1/orders_common.py"
OUTBOX = "backend/app/core/outbox.py"
MAIN = "backend/app/main.py"
PUSH = "backend/app/services/push_events.py"
CENTER = "backend/app/services/message_center.py"
PUSHTRUST = "android/app/src/main/java/com/tapmoay/sorders/core/PushTrust.kt"
ALERT = "android/app/src/main/java/com/tapmoay/sorders/core/NewOrderAlert.kt"
HUB = "android/app/src/main/java/com/tapmoay/sorders/core/RealtimeHub.kt"
DELETED_KT = "android/app/src/main/java/com/tapmoay/sorders/ui/order/OrderDeleted.kt"
DETAIL = "android/app/src/main/java/com/tapmoay/sorders/ui/order/OrderDetailScreen.kt"

#: 被中断时的安全副本（R3-07b 的延伸）：本脚本要改源码树，万一进程被外面杀掉（超时、Ctrl-C），
#: 注入就留在树里了 —— 本项目已经真的发生过一次。所以每次运行**先把原文另存一份**，
#: 下次启动时若发现残留，先还原再说。

ENQUEUE_BLOCK = re.compile(r"\n[ \t]*outbox\.enqueue\((?:[^()]|\([^()]*\))*\)\n")
DELETED_BRANCH = re.compile(r'"order\.deleted" -> \{\n(?:[^\n]*\n)*?[ \t]*\}\n')
DETAIL_BRANCH = re.compile(
    r"\n[ \t]*vm\.order == null && vm\.error != null && OrderDeleted\.isDeletedNotice\(vm\.error\) ->[^\n]*\n"
)


def drop_first_enqueue(src: str) -> str:
    """把第一处 outbox.enqueue(...) 整块删掉（含跨行的载荷字典）。"""
    return ENQUEUE_BLOCK.sub("\n", src, count=1)


def mute_deleted_announce(src: str) -> str:
    """只把 `order.deleted` 那一支的播报删掉。

    ⚠️ 不能直接 replace 那一行文本：`order.assigned` / `order.revoked` 两支里
    有一行**逐字相同**的 announce，replace(count=1) 会打在**第一处**（assigned）上 ——
    删了一个跟本单无关的分支，判据当然不红（假绿）。
    """
    m = DELETED_BRANCH.search(src)
    if not m:
        return src
    block = re.sub(r'\n[ \t]*announce\(e\.type, orderIdOf\(e\.data\), ""\)', "", m.group(0), count=1)
    return src[: m.start()] + block + src[m.end() :]


def hollow_deleted_branch(src: str) -> str:
    """把 _outbox_deliver 里 orders.deleted 那一支掏成空壳（只剩 return）。"""
    return re.sub(
        r'(if event\.event_type == "orders\.deleted":\n)(?:[ \t]{8}[^\n]*\n)+',
        r"\1        return\n",
        src,
        count=1,
    )


def move_detail_branch_after_error(src: str) -> str:
    """把"这是被删的单"那一支挪到 ErrorView 那一支**之后**（顺序错了就应该是小事化无）。"""
    m = DETAIL_BRANCH.search(src)
    if not m:
        return src
    block = m.group(0)
    rest = src[: m.start()] + "\n" + src[m.end() :]
    return re.sub(
        r"(\n[ \t]*vm\.order == null && vm\.error != null -> ErrorView\([^\n]*\n)",
        lambda mm: mm.group(1) + block.lstrip("\n"),
        rest,
        count=1,
    )


# (说明, 相对路径, 注入函数, 期望红的方式)
#   期望红的方式："check" = 红线必须报红；"check+pytest" = 红线与后端测试都要报红
CASES: list[tuple[str, str, object, str]] = [
    # ---------- 后端：发得出 ----------
    (
        "软删端点不发事件了（把事件名改掉）—— TA-05 的病根就是这个",
        LIFECYCLE,
        lambda s: s.replace('"orders.deleted"', '"orders.deletedX"', 1),
        "check+pytest",
    ),
    (
        "恢复端点不发事件了（静默回归）",
        LIFECYCLE,
        lambda s: s.replace('"orders.restored"', '"orders.restoredX"', 1),
        "check+pytest",
    ),
    (
        "软删端点的 outbox.enqueue 整块被删掉（连载荷一起）",
        LIFECYCLE,
        drop_first_enqueue,
        "check+pytest",
    ),
    (
        "聚合根登记被删：orders.deleted 不在 AGGREGATE_KEY 里",
        OUTBOX,
        lambda s: re.sub(r'\n[ \t]*"orders\.deleted": "order_id",', "", s, count=1),
        "check",
    ),
    (
        "聚合根登记被删：orders.restored 不在 AGGREGATE_KEY 里",
        OUTBOX,
        lambda s: re.sub(r'\n[ \t]*"orders\.restored": "order_id",', "", s, count=1),
        "check",
    ),
    (
        "派发表那一支被掏成空壳（登记了、什么都不做）",
        MAIN,
        hollow_deleted_branch,
        "check+pytest",
    ),
    (
        "push_events 的薄包装没了（事件入队但没人能投）",
        PUSH,
        lambda s: s.replace("async def push_order_deleted(", "async def push_order_deletedXX(", 1),
        "check",
    ),
    (
        "站内信/实时信号的发布器整个没了",
        CENTER,
        lambda s: s.replace("async def publish_order_deleted(", "async def publish_order_deletedXX(", 1),
        "check+pytest",
    ),
    (
        "发布器里只发站内信、**不发实时信号**（这一条正是 TA-05 的失效形状：有通知、列表不动）",
        CENTER,
        lambda s: re.sub(
            r'\n[ \t]*await emit_realtime\(uid, \{"type": "order\.deleted"[^\n]*\n', "\n", s, count=1
        ),
        "check+pytest",
    ),
    # ---------- 后端：说得对 ----------
    (
        "软删详情的 404 文案退回「订单不存在」—— TA-06 的病根就是这个",
        COMMON,
        lambda s: s.replace("_deleted_order_notice(order, role, current)", "PLAIN_NOT_FOUND_NOTICE", 1),
        "check+pytest",
    ),
    (
        "把「当事人」这一层放宽成「谁都告诉他」（泄露有一张看不见的已删除单）",
        COMMON,
        lambda s: s.replace("    if not mine:\n", "    if False:\n", 1),
        "check+pytest",
    ),
    # ---------- 安卓：认得出 ----------
    (
        "安卓事件白名单里没有 order.deleted（实时信号到了也被 PushTrust 丢进垃圾桶）",
        PUSHTRUST,
        lambda s: re.sub(r'\n[ \t]*"order\.deleted",', "", s, count=1),
        "check",
    ),
    (
        "安卓事件白名单里没有 order.restored",
        PUSHTRUST,
        lambda s: re.sub(r'\n[ \t]*"order\.restored",', "", s, count=1),
        "check",
    ),
    (
        "被删的单不认成「任务被撤回」（司机听不见那一声）",
        ALERT,
        lambda s: s.replace(
            '"order.revoked", "order.cancelled", "order.deleted" -> AlertEvent(',
            '"order.revoked", "order.cancelled" -> AlertEvent(',
            1,
        ),
        "check",
    ),
    (
        "shouldStop 不认被删的单（活没了还在喊「来订单了」）",
        ALERT,
        lambda s: re.sub(r'\n[ \t]*"order\.deleted",(?=\n[ \t]*// 派单员的三个)', "", s, count=1),
        "check",
    ),
    (
        "实时分支只刷新不播报（列表悄悄少一张，司机一句提示都没有）",
        HUB,
        mute_deleted_announce,
        "check",
    ),
    (
        "实时分支被换成一整块注释（验证判据真的不吃注释 —— 本项目栽过这个坑）",
        HUB,
        lambda s: DELETED_BRANCH.sub('// "order.deleted" -> { _refreshOrders.tryEmit(Unit) }\n', s, count=1),
        "check",
    ),
    (
        "恢复也要播报（恢复不是「该司机动手」的事，不该打断他）",
        HUB,
        lambda s: s.replace(
            '"order.restored" -> _refreshOrders.tryEmit(Unit)',
            '"order.restored" -> { _refreshOrders.tryEmit(Unit); announce(e.type, orderIdOf(e.data), "") }',
            1,
        ),
        "check",
    ),
    (
        "安卓与后端的文案对不上（HINTS 少一个字，「靠 contains 认」就断了）",
        DELETED_KT,
        lambda s: s.replace("如需找回请联系派单员从回收站恢复。", "如需找回请联系派单员。", 1),
        "check",
    ),
    (
        "详情页那屏给的是「重试」而不是「返回」（重试一百次也找不回一张被删的单）",
        DELETED_KT,
        lambda s: s.replace('Text("返回")', 'Text("重试")', 1),
        "check",
    ),
    (
        "详情页那一支被整个删掉（又只剩「订单不存在」+「重试」）",
        DETAIL,
        lambda s: DETAIL_BRANCH.sub("\n", s, count=1),
        "check",
    ),
    (
        "那一支排在 ErrorView **之后**（顺序错了就等于没写）",
        DETAIL,
        move_detail_branch_after_error,
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

    if SAFETY.exists():
        print("⚠️ 上一次运行被中断，正在用安全副本还原源码树…")
        rels = [x for x in (SAFETY / "manifest.txt").read_text(encoding="utf-8").splitlines() if x.strip()]
        for i, rel in enumerate(rels):
            (ROOT / rel).write_bytes((SAFETY / f"{i:02d}.bin").read_bytes())
            print("   ↩ 已还原 " + rel)
        shutil.rmtree(SAFETY)

    code, out = run_check()
    if code != 0:
        print("❌ 前提不成立：源码完好时红线就没过")
        print(out[-1500:])
        return 1
    code, out = run_pytest()
    if code != 0:
        print("❌ 前提不成立：源码完好时后端测试就没过")
        print(out[-1500:])
        return 1
    print("✅ 前提：源码完好时，红线与后端测试都是绿的")

    # 先给每个将被注入的文件留一份原文（被外面杀掉时靠它还原）
    SAFETY.mkdir(parents=True, exist_ok=True)
    seen: list[str] = []
    for _label, rel, _mutate, _expect in CASES:
        if rel in seen:
            continue
        seen.append(rel)
        (SAFETY / f"{len(seen) - 1:02d}.bin").write_bytes((ROOT / rel).read_bytes())
    (SAFETY / "manifest.txt").write_text("\n".join(seen) + "\n", encoding="utf-8")

    for label, rel, mutate, expect in CASES:
        path = ROOT / rel
        original_bytes = path.read_bytes()
        original = original_bytes.decode("utf-8").replace(chr(13) + chr(10), chr(10))
        mutated = mutate(original)
        if mutated == original:
            fails.append(f"{label}：注入没生效（锚点变了，请更新本脚本）：{rel}")
            continue
        try:
            path.write_text(mutated, encoding="utf-8", newline="")
            c_code, c_out = run_check()
            t_code, t_out = ("", "") if expect == "check" else run_pytest()
        finally:
            path.write_bytes(original_bytes)
        # R3-07b：还原**当场核对**（不是「看起来还原了」）—— 对不上就记账，别让坏代码留在树里
        if path.read_bytes() != original_bytes:
            fails.append("还原后与快照不一致（注入污染了源码树）：" + str(path))

        red_check = c_code != 0
        red_test = t_code != 0 if expect == "check+pytest" else True
        if red_check and red_test:
            which = "红线" + ("+后端测试" if expect == "check+pytest" else "")
            print(f"✅ 注入「{label}」→ {which} 报红")
        else:
            why = "红线没红" if not red_check else "红线红了（但测试没红）"
            if expect == "check":
                why = ("红线没红" if not red_check else "红线红了") + "（本用例只查红线）"
            fails.append(f"{label}：注入后 {why}（红线码={c_code} 测试码={t_code!r}）")
            for ln in (c_out or "").splitlines()[-6:]:
                print("     [check] " + ln.strip())
            if expect == "check+pytest":
                for ln in (t_out or "").splitlines()[-6:]:
                    print("     [pytest] " + ln.strip())

    if SAFETY.exists():
        shutil.rmtree(SAFETY)  # 全部还原过了，安全副本可以清掉

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
