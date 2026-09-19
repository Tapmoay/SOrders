"""反向验证「离线送达队列不许把追加备注写两遍」这条红线**真的会红**（2026-09-19 审计 H5）。

四类破坏，每一类都必须单独让红线报红：
| 注入 | 证明的是 |
|---|---|
| 队列项类型里去掉 `noteAppended` 标记 | 判据真的在看"有没有持久化标记" |
| 标记只在内存里改、不 put 回库 | 判据不满足于"有个方法"（假持久化 = 重启就丢，照样重复追加） |
| 同步循环里去掉 `!it.noteAppended` 判断 | 判据真的在看同步路径（而不是只看工具文件） |
| 把 `markNoteAppended` 挪到上传之后 | 判据真的在查**顺序**（顺序反了等于没记） |

用法：python _tools/qa/_reverse_verify_offline_queue.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_offline_queue.py"
QUEUE = "frontend/src/utils/offlineDeliveryQueue.ts"
VIEW = "frontend/src/views/driver/DriverOpenOrders.vue"

CASES: list[tuple[str, str, object]] = [
    (
        "队列项类型里去掉「备注已写」标记",
        QUEUE,
        lambda s: s.replace("  noteAppended?: boolean\n", "", 1),
    ),
    (
        "标记只在内存里改、不 put 回 IndexedDB（假持久化）",
        QUEUE,
        lambda s: s.replace("        row.noteAppended = true\n        st.put(row)\n", "        row.noteAppended = true\n", 1),
    ),
    (
        "同步循环里不再判标记（重试就重复追加）",
        VIEW,
        lambda s: s.replace("if (note && !it.noteAppended) {", "if (note) {", 1),
    ),
    (
        "把落标记挪到传照片**之后**（顺序反了 = 上传失败仍会重复追加）",
        VIEW,
        lambda s: s.replace("          await markNoteAppended(it.id)\n", "", 1).replace(
            "        await removeOfflineQueueItem(it.id)\n",
            "        await markNoteAppended(it.id)\n        await removeOfflineQueueItem(it.id)\n",
            1,
        ),
    ),
]


def read_src(p: Path) -> tuple[str, bool]:
    data = p.read_bytes()
    return data.decode("utf-8").replace("\r\n", "\n"), b"\r\n" in data


def write_src(p: Path, text: str, crlf: bool) -> None:
    data = text.replace("\r\n", "\n")
    if crlf:
        data = data.replace("\n", "\r\n")
    p.write_bytes(data.encode("utf-8"))


def run_check() -> int:
    p = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return p.returncode


def main() -> int:
    fails: list[str] = []
    if run_check() != 0:
        print("❌ 前提不成立：源码完好时这条红线就没过")
        return 1
    print("✅ 前提：源码完好时红线是绿的")

    touched = sorted({rel for _l, rel, _m in CASES})
    originals = {rel: (ROOT / rel).read_bytes() for rel in touched}
    crlfs = {rel: b"\r\n" in originals[rel] for rel in touched}

    for label, rel, mutate in CASES:
        path = ROOT / rel
        plain = originals[rel].decode("utf-8").replace("\r\n", "\n")
        mutated = mutate(plain)  # type: ignore[operator]
        if mutated == plain:
            fails.append(f"{label}：注入没生效（锚点变了，请更新本脚本）")
            print(f"  [SKIP] {label}")
            continue
        try:
            write_src(path, mutated, crlfs[rel])
            red = run_check() != 0
        finally:
            path.write_bytes(originals[rel])
        if red:
            print(f"  [OK] {label} → 红线报红")
        else:
            fails.append(f"{label}：注入之后红线**仍然全绿**（判据没牙）")
            print(f"  [MISS] {label} → 全绿")

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
