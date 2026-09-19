"""红线：**离线送达队列不许把「追加备注」写两遍**（2026-09-19 审计 H5）。

## 缺陷形状
司机在地下车库点了「完成订单」→ 进离线队列。同步是**两步**：
先 `POST /orders/{id}/driver-note`（追加内部备注），再 `POST /orders/{id}/complete-with-upload`（传照片+送达）。
上传失败是常事（信号差），而**重试是整条重来** —— 不看标记就再 append 一次，
订单的内部备注里同一句话会出现两遍、三遍（"货主让放门口"重复三行）。
派单员正是靠内部备注判断现场发生了什么，而这条数据一旦重复**没有任何界面会提示**。

## 判据（清单自己算）
1. 队列项类型里必须有"备注已写"的持久化标记（`noteAppended`）；
2. 队列工具里必须有写这个标记的方法，且它是 `put`（真落库，不是只改内存对象）；
3. 同步循环里 append 之前必须判这个标记（`!it.noteAppended`），
   且**先落标记、再传照片**（顺序反了等于没记 —— 上传失败后重试仍会重复追加）。

用法：python _tools/qa/_check_offline_queue.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
QUEUE = ROOT / "frontend/src/utils/offlineDeliveryQueue.ts"
VIEW = ROOT / "frontend/src/views/driver/DriverOpenOrders.vue"

fails: list[str] = []
passes = 0


def ok(label: str, cond: bool, detail: str = "") -> None:
    global passes
    if cond:
        passes += 1
        print(f"  [OK]   {label}")
    else:
        fails.append(label + (f" —— {detail}" if detail else ""))
        print(f"  [FAIL] {label}" + (f" —— {detail}" if detail else ""))


def main() -> int:
    for p in (QUEUE, VIEW):
        if not p.exists():
            print(f"❌ 找不到 {p.relative_to(ROOT)}（改名/移动了？判据要跟着改，不许静默跳过）")
            return 1
    q = QUEUE.read_text(encoding="utf-8")
    v = VIEW.read_text(encoding="utf-8")

    print("队列工具（offlineDeliveryQueue.ts）")
    ok("队列项类型里有「备注已写」的持久化标记", re.search(r"noteAppended\?:", q) is not None)
    ok("有写这个标记的方法", re.search(r"export async function markNoteAppended\(", q) is not None)
    # ⚠️ 必须**只看这个函数体**：`st.put(row)` 在 bumpRetry / setQueueItemError 里也有，
    #    不限定范围的话，"方法里根本没写回库"这种注入照样绿（反向验证抓到过一次）。
    m = re.search(r"export async function markNoteAppended\(.*?\n\}", q, re.S)
    body = m.group(0) if m else ""
    ok("标记是**落库**的（这个函数体里真的 put 回 IndexedDB）",
       "noteAppended = true" in body and "st.put(row)" in body)

    print("\n同步循环（DriverOpenOrders.vue）")
    ok("append 之前判了标记（`!it.noteAppended`）", "!it.noteAppended" in v)
    ok("调了 markNoteAppended", re.search(r"await markNoteAppended\(", v) is not None)
    # 顺序：append → markNoteAppended → completeOrderWithUpload
    i_append = v.find("await appendDriverNote(it.orderId, note)")
    i_mark = v.find("await markNoteAppended(it.id)")
    i_upload = v.find("await completeOrderWithUpload(it.orderId")
    ok("三步顺序正确：追加备注 → 落标记 → 传照片",
       -1 < i_append < i_mark < i_upload, f"位置 {i_append}/{i_mark}/{i_upload}")

    print("\n" + "=" * 60)
    if fails:
        print(f"❌ {len(fails)} 项不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"✅ 全部 {passes} 项通过：离线重试不会把内部备注写两遍。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
