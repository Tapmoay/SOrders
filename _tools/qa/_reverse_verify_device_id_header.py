"""FEAT-0018 客户端判据的反向验证：6 种破坏方式，每一条都必须把判据打红。

为什么必须反验：`_check_device_id_header.py` 钉的全是"源码里有没有这一行/这一句"，
而**判据自己写错**（切片切到文件尾、清单手写过时、量词少一个括号）时它照样会绿 ——
绿得看不出来。这份脚本按"这一块最可能怎么坏"逐条注入，证明每条钉子真的咬得住。

每条注入对应哪种坏法（与判据的编号一一对应）：
① 把请求头那一行删掉 → 后端再也认不出设备（C4/C5/C8 必须红）；
② 在页面里各写一遍头名 → "统一注入点"退化成"每页一份"（C7 必须红）；
③ 把 403 原话截断 → 用户看不到"最早那台什么时候能换"（D3/D4 必须红）；
④ 把「全部解冻」入口换成一句普通文字 → 司机换手机最常用的一下没了（E21 必须红）；
⑤ 「还没拉到」回落成 0 台 → 名额显示成"空着"（E6 必须红）；
⑥ 顺手读一个硬件标识 → 隐私红线（B2 必须红）。

配套：`_tools/qa/_reverse_verify_device_id_header.py`（6 种破坏方式全被抓）与
`_tools/qa/_check_device_id_header.py` 成对存在；判据 docstring 里那份「6 种破坏」的自述
由 `_check_reverse_verify_anchors.py` 与本文件的 MUTATIONS 条数对账。

⚠️ 本脚本会**临时改写源码再逐字节还原**（每条注入前后都核对原文）。
   硬中断（Ctrl+C / 关窗口）会留下注入后的源码，跑
   `python _tools/qa/_check_reverse_verify_anchors.py --restore` 可以还原。

用法：python _tools/qa/_reverse_verify_device_id_header.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_device_id_header.py"
AND = "android/app/src/main/java/com/tapmoay/sorders"

# (说明, 目标文件相对路径, 被替换的原文, 替换成什么, 期望变红的那条判据)
MUTATIONS: list[tuple[str, str, str, str, str]] = [
    (
        "① 删掉唯一那处设备头（接口照样 200，只是后端再也认不出这台设备）",
        AND + "/core/ApiClient.kt",
        '                        if (device != null) header(DeviceIdentity.HEADER, device)\n',
        "",
        "C4",
    ),
    (
        "② 在页面里各写一遍头名（看着能用，别的接口全没有）",
        AND + "/ui/dispatcher/AccountManageScreen.kt",
        "        RosterPhoneRowOf(u)\n",
        '        RosterPhoneRowOf(u)\n        val xDeviceHeader = "X-Device-Id"\n',
        "C7",
    ),
    (
        "③ 把 403 原话截断（日期与出路一起没了）",
        AND + "/core/ApiClient.kt",
        "        if (zh != null) return zh\n",
        '        if (zh != null) return zh.take(12) + "…"\n',
        "D4",
    ),
    (
        "④ 把「全部解冻」入口拿掉（司机换手机只能一台一台点）",
        AND + "/ui/dispatcher/AccountManageScreen.kt",
        '                    Text("全部解冻（" + active.size + " 台）", fontSize = 15.sp)',
        '                    Text("解冻", fontSize = 15.sp)',
        "E21",
    ),
    (
        "⑤ 「还没拉到」回落成 0 台（名额看着空着，其实是被拦掉的）",
        AND + "/ui/dispatcher/AccountManageViewModel.kt",
        "    rows?.count { it.active } ?: UNKNOWN_DEVICE_COUNT",
        "    rows?.count { it.active } ?: 0",
        "E6",
    ),
    (
        "⑥ 顺手读一个硬件标识（Android 10+ 拿不到，还踩隐私红线）",
        AND + "/core/DeviceId.kt",
        "    fun newInstallId(): String = UUID.randomUUID().toString()",
        "    fun newInstallId(): String = android.telephony.TelephonyManager::class.java.simpleName",
        "B2",
    ),
]


def run_check() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(CHECK)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ROOT),
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def verdict(expect: str, code: int, out: str) -> str:
    if code == 0:
        return "注入之后判据还是绿的"
    if expect not in out:
        return "红了，但不是预期那一条（没看到 " + expect + "）"
    return ""


def main() -> int:
    base_code, base_out = run_check()
    if base_code != 0:
        print("❌ 基线就是红的 —— 先让 _check_device_id_header.py 全绿再来反验：")
        print(base_out[-2000:])
        return 2

    bad = 0
    for desc, rel, old, new, expect in MUTATIONS:
        p = ROOT / rel
        data = p.read_bytes()
        crlf = b"\r\n" in data
        o = old.replace("\n", "\r\n") if crlf else old
        n = new.replace("\n", "\r\n") if crlf else new
        src = data.decode("utf-8")
        if src.count(o) != 1:
            print("[SKIP] " + desc + " —— 锚点腐烂（命中 %d 次）" % src.count(o))
            bad += 1
            continue
        try:
            p.write_bytes(src.replace(o, n, 1).encode("utf-8"))
            code, out = run_check()
        finally:
            p.write_bytes(data)
            if p.read_bytes() != data:
                raise SystemExit("还原失败：" + rel + "（跑 _check_reverse_verify_anchors.py --restore）")
        why = verdict(expect, code, out)
        if why:
            print("[FAIL] " + desc + " —— " + why)
            bad += 1
        else:
            print("[OK]   " + desc + " → 判据变红（" + expect + "）")

    if bad:
        print("❌ %d/%d 条成立" % (len(MUTATIONS) - bad, len(MUTATIONS)))
        return 1
    print("✅ %d/%d 条全部成立：删头 / 每页各写一遍 / 截断原话 / 拿掉全部解冻 / 画成 0 台 / 读硬件标识，都被判据抓住" % (len(MUTATIONS), len(MUTATIONS)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())