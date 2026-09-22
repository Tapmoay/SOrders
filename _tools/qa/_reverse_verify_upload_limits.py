"""反向验证「上传必须限量读」这条红线**真的会红**（2026-09-23 复核 G8）。

## 为什么这条要反向验证
它的判据是"函数体里有没有 `read_limited(`"，有一类**看起来在查、其实没查**的失效方式：
- 调用点被改回 `await file.read()`（就是这条红线要防的那个形状）；
- **限量读的实现本身**被改坏（读了但不判、或改回无参数 `read()`）——
  这时"所有调用点都合规"是一句空话：它们调的是一个不设防的函数；
- 豁免表被当成万能口子（把一个其实自己读了的函数挂上去，或挂一个已不存在的名字）。

所以四种破坏各注入一次。

用法：python _tools/qa/_reverse_verify_upload_limits.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_upload_limits.py"

CASES: list[tuple[str, str, object]] = [
    (
        "一个调用点改回「先把整个请求体读进内存」",
        "backend/app/api/v1/products.py",
        lambda s: s.replace(
            "    raw = await read_limited(file, MAX_IMAGE_BYTES, detail=\"图片过大（最大 4MB）\")",
            "    raw = await file.read()",
            1,
        ),
    ),
    (
        "限量读的实现被改回无参数 read（读了但上限没了）",
        "backend/app/core/upload_read.py",
        lambda s: s.replace("raw = await file.read(limit + 1)", "raw = await file.read()", 1),
    ),
    (
        "限量读的实现读了但不再拦（越界也放行）",
        "backend/app/core/upload_read.py",
        lambda s: s.replace("    if len(raw) > limit:", "    if False:", 1),
    ),
    (
        "豁免表被当成万能口子（把一个其实自己限量读的函数挂上去）",
        "_tools/qa/_check_upload_limits.py",
        lambda s: s.replace(
            "DELEGATES: dict[str, str] = {\n",
            "DELEGATES: dict[str, str] = {\n"
            '    "parse_sheet": "注入：假装这个函数只是转发",\n',
            1,
        ),
    ),
    (
        "调用点漏掉 await（静态看着「调了限量读」，实际拿到的是协程 → 端点 500）",
        "backend/app/api/v1/shipper.py",
        lambda s: s.replace(
            "    raw = await read_limited(file, MAX_IMAGE_BYTES, detail=\"图片过大（最大 4MB）\")",
            "    raw = read_limited(file, MAX_IMAGE_BYTES, detail=\"图片过大（最大 4MB）\")",
            1,
        ),
    ),
]


def run_check(target: Path | None = None) -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(target or CHECK)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    fails: list[str] = []
    code, out = run_check()
    if code != 0:
        print("❌ 前提不成立：源码完好时这条红线就没过")
        print(out[-1200:])
        return 1
    print("✅ 前提：源码完好时红线是绿的")

    touched = sorted({rel for _l, rel, _m in CASES})
    originals = {rel: (ROOT / rel).read_bytes() for rel in touched}

    for label, rel, mutate in CASES:
        path = ROOT / rel
        original_bytes = originals[rel]
        mutated = mutate(original_bytes.decode("utf-8"))
        if mutated == original_bytes.decode("utf-8"):
            fails.append(f"{label}：注入没生效（锚点变了，请更新本脚本）")
            print(f"  [SKIP] {label}")
            continue
        tmp: Path | None = None
        try:
            if path == CHECK:
                tmp = path.with_suffix(".py.injected")
                tmp.write_bytes(mutated.encode("utf-8"))
                code, out = run_check(tmp)
            else:
                path.write_bytes(mutated.encode("utf-8"))
                code, out = run_check()
        finally:
            if tmp is not None and tmp.exists():
                tmp.unlink()
            path.write_bytes(original_bytes)
        if code != 0:
            print(f"  [OK] {label} → 红线报红")
        else:
            fails.append(f"{label}：注入之后红线**仍然全绿**（判据没牙）")
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
