"""反向验证「PATCH 体里非空默认值字段必须显式回填」这条红线**真的会红**（W1 形状）。

三类破坏：
| 注入 | 证明的是 |
|---|---|
| 去掉 `updateAddress` 里的 `imageUrls = cur.imageUrls`（**本轮真抓到的那个缺陷**） | 判据真的在看**这个**函数 |
| 把 `LocationCreateRequest` 的一行回填删掉 | 判据不是只盯着地址那一处 |
| 给某个 `*Request` 加一个**非空默认值**字段（等价于"新增一个会被永远发出去的默认值"） | 判据会跟着 DTO 变化走（而不是一张写死的名单） |

用法：python _tools/qa/_reverse_verify_ai_dto_defaults.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_ai_dto_defaults.py"
SVC = "android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteDataSource.kt"
DTOS = "android/app/src/main/java/com/tapmoay/sorders/data/remote/dto/Dtos.kt"

CASES: list[tuple[str, str, object]] = [
    (
        "去掉地址 PATCH 里的 imageUrls 回填（每次改线路都清空照片）",
        SVC,
        lambda s: s.replace("                imageUrls = cur.imageUrls,\n", "", 1),
    ),
    (
        "去掉地点 PATCH 里的 imageUrls 回填",
        SVC,
        lambda s: s.replace("                imageUrls = cur.imageUrls,\n", "", 1),
    ),
    (
        "给 AddressCreateRequest 再加一个非空默认值字段（新的「永远发出去」的默认值）",
        DTOS,
        # ⚠️ 锚点必须**唯一**：`@SerialName("image_urls") val imageUrls…` 这一行在 Dtos.kt 里
        #    出现了不止一次（AddressDto / 地点 / 地址请求），只按它注入会落到别的 DTO 上，
        #    判据没反应，"没牙"的帽子就扣错了（实测踩到）。用 origin_lng + image_urls 两行定位。
        lambda s: s.replace(
            '    @SerialName("origin_lng") val originLng: String? = null,\n'
            '    @SerialName("image_urls") val imageUrls: List<String> = emptyList(),\n',
            '    @SerialName("origin_lng") val originLng: String? = null,\n'
            '    @SerialName("image_urls") val imageUrls: List<String> = emptyList(),\n'
            '    @SerialName("probe_new_field") val probeNewField: String = "",\n',
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
    r = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return r.returncode


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
