# -*- coding: utf-8 -*-
"""反向验证「退货要告诉经手那张单的司机」这条红线**真的会红**（BUG-0005 / P27）。

## 为什么这条要反向验证
它的判据大多是「某个字面量必须恰好一份 / 某一支必须排在前面 / 某句话里不许出现某种说法」，
这类判据有三种典型失效方式，每一种都单独证明一次会红：

1. **判据变成空转**：事件名改了、聚合根映射换了、派发表那一支的条件改了之后，
   判据必须报红（「恰好一份」那一条**0 处也红**，不只是「在不在」）。
2. **顺序 / 取值型判据最容易假绿**：把 `event_id` 从幂等键里去掉，第一条消息照样发得出去，
   只有「同一张单退第二次」才会被静默吞掉 —— 扫「幂等键里有没有 idem_key」永远是绿的。
   同理：「已完成」那一档只查 `DELIVERED` 时，页面不报错、列表也不空（别的单还在），
   只有当事人翻不到那张单。
3. **一句话换一种说法照样编译**：正文里那句口径换成「这一单的运费照结」，
   后端 `api/v1/driver_bills.py:66-67` 把那件事挂在待拍板上 —— 判据必须拦住它。

另外几条打的是「客户端那一行时间夹在送达与撤销之间」与判据自己：
「退货」时间行换一个字段（`returnedAt` 写成别的）、治理文档里的登记被撤掉，
以及**判据自己的 REVERSE 常量被改名**（自指用例）。

⚠️ 快照 / 还原按**字节**做，跑完逐字节核对（本项目栽过「注入把 bug 留在源码里」）。

用法：python _tools/qa/_reverse_verify_driver_return_notice.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_driver_return_notice.py"
CHECK_REL = "_tools/qa/_check_driver_return_notice.py"

#: Windows 上这些文件可能是 CRLF：按字节快照、归一后再替换、写回时按原样还原
#: （⛔ 不要写反斜杠转义，用字节常量拼；本项目在这个坑上栽过两次）
CR = bytes((13,))
LF = bytes((10,))
CRLF = CR + LF

RETURN = "backend/app/services/order_return.py"
OUTBOX = "backend/app/core/outbox.py"
MAIN = "backend/app/main.py"
PUSH = "backend/app/services/push_events.py"
CENTER = "backend/app/services/message_center.py"
DETAIL = "android/app/src/main/java/com/tapmoay/sorders/ui/order/OrderDetailScreen.kt"
DRIVER_VM = "android/app/src/main/java/com/tapmoay/sorders/ui/driver/DriverOrdersViewModel.kt"
DOMAINS = "docs/DOMAIN_BOUNDARIES.md"

#: (说明, 相对路径, 替换函数, 期望在输出里出现的关键词 —— 空串 = 只要非零退出)
CASES: list[tuple[str, str, object, str]] = [
    (
        "① 退货服务里那个事件名被改掉（发件箱从此收不到这条退货）",
        RETURN,
        lambda s: s.replace(
            chr(34) + "returns.order_returned" + chr(34) + ",",
            chr(34) + "returns.order_returned_GONE" + chr(34) + ",",
            1,
        ),
        "唯一入口",
    ),
    (
        "② 发件箱的聚合根映射被改成申请单（直连退货没有申请单 → 派发时找不到聚合根）",
        OUTBOX,
        lambda s: s.replace(
            chr(34) + "returns.order_returned" + chr(34) + ": " + chr(34) + "order_id" + chr(34) + ",",
            chr(34) + "returns.order_returned" + chr(34) + ": " + chr(34) + "request_id" + chr(34) + ",",
            1,
        ),
        "聚合根",
    ),
    (
        "③ 派发表里那一支的条件被改掉（事件进了发件箱却没人消费）",
        MAIN,
        lambda s: s.replace(
            "if event.event_type == " + chr(34) + "returns.order_returned" + chr(34) + ":",
            "if event.event_type == " + chr(34) + "returns.order_returned_GONE" + chr(34) + ":",
            1,
        ),
        "派发表里有",
    ),
    (
        "④ 推送函数被改名（派发表调用的名字与定义对不上）",
        PUSH,
        lambda s: s.replace(
            "async def push_order_returned_to_driver(",
            "async def push_order_returned_to_driver_GONE(",
            1,
        ),
        "推送函数",
    ),
    (
        "⑤ 幂等键里的 event_id 被去掉（同一张单退第二次，消息被当成重复吞掉）",
        CENTER,
        lambda s: s.replace(
            chr(34) + ":" + chr(34) + " + str(order_id) + " + chr(34) + ":" + chr(34) + " + str(event_id),",
            chr(34) + ":" + chr(34) + " + str(order_id),",
            1,
        ),
        "幂等",
    ),
    (
        "⑥ 正文里那句口径被换成「这一单的运费照结」（替待拍板的产品决策下结论）",
        CENTER,
        # ⚠️ 必须替换**正文那一句**（`已经跑完，` 是这个函数正文独有的前缀）：
        #    直接用「账单不会被退货改动」会先命中它 docstring 里那句说明，正文那句还在 → 判据照样绿。
        lambda s: s.replace(
            "已经跑完，账单不会被退货改动（有疑问看",
            "已经跑完，这一单的运费照结（有疑问看",
            1,
        ),
        "照结",
    ),
    (
        "⑦ 订单详情里那一行时间换成别的字段（退货那一步在流水里消失）",
        DETAIL,
        lambda s: s.replace(
            "order.returnedAt?.let { TimeRow(" + chr(34) + "退货" + chr(34) + ", it) }",
            "order.returnedAtGone?.let { TimeRow(" + chr(34) + "退货" + chr(34) + ", it) }",
            1,
        ),
        "流转记录",
    ),
    (
        "⑧ 司机端取数不再与探测同源（退回「已完成」那一档只查已送达）",
        DRIVER_VM,
        lambda s: s.replace(
            "else FINISHED_STATUSES",
            "else listOf(" + chr(34) + "DELIVERED" + chr(34) + ")",
            1,
        ),
        "同源",
    ),
    (
        "⑨「已完成这一档」被缩回只认已送达（整单退货的单从司机列表里消失）",
        DRIVER_VM,
        lambda s: s.replace(
            "listOf(" + chr(34) + "DELIVERED" + chr(34) + ", " + chr(34) + "RETURNED" + chr(34) + ")",
            "listOf(" + chr(34) + "DELIVERED" + chr(34) + ")",
            1,
        ),
        "已完成这一档",
    ),
    (
        "⑩ 领域边界文档里的登记被撤掉（事件又变成没有主的野事件）",
        DOMAINS,
        lambda s: s.replace(
            ", returns.order_returned",
            ", returns.order_returned_GONE",
            1,
        ),
        "退货域",
    ),
    (
        "⑪ 判据自己的 REVERSE 常量被改名（防它指向一个不存在的脚本还照样绿）",
        CHECK_REL,
        lambda s: s.replace(
            "REVERSE = " + chr(34) + "_tools/qa/_reverse_verify_driver_return_notice.py" + chr(34),
            "REVERSE = " + chr(34) + "_tools/qa/_reverse_verify_driver_return_notice_gone.py" + chr(34),
            1,
        ),
        "反向验证",
    ),
]


def run_check() -> tuple[int, str]:
    q = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return q.returncode, (q.stdout or "") + (q.stderr or "")


def main() -> int:
    fails: list[str] = []
    code, out = run_check()
    if code != 0:
        print("❌ 前提不成立：源码完好时这条红线就没过")
        print(out[-1500:])
        return 1
    print("✅ 前提：源码完好时红线是绿的（判据自己 50 项）")

    touched = sorted({rel for _l, rel, _m, _e in CASES})
    originals = {rel: (ROOT / rel).read_bytes() for rel in touched}

    for label, rel, mutate, expect in CASES:
        path = ROOT / rel
        original_bytes = originals[rel]
        crlf = CRLF in original_bytes
        plain = original_bytes.decode("utf-8").replace(CRLF.decode(), LF.decode())
        mutated = mutate(plain)  # type: ignore[operator]
        if mutated == plain:
            fails.append(f"{label}：注入没生效（锚点变了，请更新本脚本）")
            print(f"  [SKIP] {label}")
            continue
        try:
            out_txt = mutated
            if crlf:
                out_txt = out_txt.replace(LF.decode(), CRLF.decode())
            path.write_bytes(out_txt.encode("utf-8"))
            code, out = run_check()
        finally:
            path.write_bytes(original_bytes)
        hit = code != 0 and (not expect or expect in out)
        if hit:
            print(f"  [OK] {label} → 报红")
        else:
            fails.append(f"{label}：注入之后没有按预期报红（退出码 {code}，期望关键词「{expect}」）")
            print(f"  [MISS] {label} → 仍然全绿")

    dirty = [rel for rel in touched if (ROOT / rel).read_bytes() != originals[rel]]
    if dirty:
        fails.append("跑完没逐字节还原：" + "、".join(dirty))
        for rel in dirty:
            (ROOT / rel).write_bytes(originals[rel])
        print("⚠️  已强制还原：" + "、".join(dirty))
    else:
        print(f"✅ 还原检查：{len(touched)} 个被碰过的文件与运行前逐字节一致")

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

