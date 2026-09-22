"""给模拟器换一具「身体」（屏宽 dp / 系统字号），用来验收小屏、平板、大字号下的卡片版式。

## ⛔ 只改 `wm size`，**绝不改 `wm density`**

2026-09-22 我踩过这个坑，代价是：截图上「全部订单」看起来样式全丢了、字体也看不清，
用户当场问「你把样式搞丢了？」——**那是我量具造成的假象，不是真机真相**。

原因：改 density 等于骗系统「这块屏是 360dpi」。App 里的 1dp 按定义仍是 1/160 英寸，
于是它在这块物理密度没变的屏幕上被渲染成**只有原来的 57% 物理大小** —— 字全变小了。
而**真实的 320dp 小屏不会这样**：320dp 的手机物理宽就是 2 英寸，同一段 14sp 的字
在大屏小屏上**物理大小一模一样**，只是占屏比例不同。

正确做法：**只把 size 改小**，让内容在物理像素上按原尺寸渲染，多出来的地方是黑边。

## ⚠️ 反过来（要的 dp 比这块屏还大，比如 600dp 平板）

模拟器的面板只有那么宽，`wm size` 大于物理尺寸时系统会把整幅画面**缩放**到面板上 ——
这一档**只能看版式（几列、有没有被拉长），不能用来判断字号的物理大小**。
脚本会明说这一点；真要判断平板的字号，得开一台真正的平板 AVD。

用法：
    python _tools/qa/_screensize.py list
    python _tools/qa/_screensize.py set small --device 5554            # 320dp 小屏
    python _tools/qa/_screensize.py set 360dp --device 5554 --font 1.3 # 窄屏 + 系统大字号
    python _tools/qa/_screensize.py set tablet --device 5554           # 600dp（见上面那条警告）
    python _tools/qa/_screensize.py reset --device 5554                # 还原（改完**立刻**还原）
    python _tools/qa/_screensize.py shot 全部订单-320dp --device 5554   # 顺手截图存档
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ADB = r"D:\APPS\sdk\platform-tools\adb.exe"
ROOT = Path(__file__).resolve().parents[2]
SHOTS = ROOT / "docs" / "screenshots" / "adapt"

#: 名字 → 宽度 dp。高度按 20:9 的现代手机比例给（高度本身不影响卡片版式判断）。
PROFILES: dict[str, int] = {
    "small": 320,      # 最窄的在售手机
    "narrow": 360,     # 国产主流窄屏
    "normal": 411,     # Pixel 6 / Pixel 2 XL（= 现在三台模拟器的默认）
    "wide": 480,
    "tablet": 600,     # 官方断点：≥600dp 才换版式
}


def adb(dev: str, *args: str, timeout: int = 30) -> str:
    p = subprocess.run([ADB, "-s", dev, *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    return (p.stdout or "") + (p.stderr or "")


def physical(dev: str) -> tuple[int, int, int]:
    """(物理宽 px, 物理高 px, 物理密度 dpi)"""
    m = dict()
    for line in adb(dev, "shell", "wm", "size").splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            m[k.strip().lower()] = v.strip()
    d = adb(dev, "shell", "wm", "density")
    dens = 0
    for line in d.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            if k.strip().lower().startswith("physical"):
                dens = int(v.strip().split()[0])
    w, h = (int(x) for x in m.get("physical size", "1080x2400").split("x"))
    return w, h, dens


def cmd_list() -> int:
    print("档位：")
    for name, dp in PROFILES.items():
        print(f"  {name:<8} {dp}dp")
    print("\n也可以直接给 `<数字>dp`，例如 320dp。")
    print("⚠️ 只改 size 不改 density；600dp 这一档是缩放渲染的，只能看版式。")
    return 0


def cmd_set(dev: str, spec: str, font: float | None) -> int:
    if spec in PROFILES:
        dp = PROFILES[spec]
    elif spec.endswith("dp") and spec[:-2].isdigit():
        dp = int(spec[:-2])
    else:
        print(f"❌ 认不出档位「{spec}」，用 `list` 看可选项")
        return 2
    pw, ph, dens = physical(dev)
    # dp → px：按**物理密度**换算，这样 1dp 仍然是 1/160 英寸（字号物理大小不变）
    px = round(dp * dens / 160)
    height = round(px * ph / pw / 2) * 2
    print(f"物理：{pw}x{ph} @ {dens}dpi")
    print(f"→ {dp}dp 需要 {px}px 宽")
    if px > pw:
        print(f"⚠️ 比面板还宽（{pw}px）：这一档会被**整幅缩放**渲染 —— "
              f"**只能看版式（几列 / 有没有被拉长），不能用来看字号的物理大小**。")
    else:
        print(f"✅ 在面板内（多出来的 {(pw - px) // 2}px 是黑边）—— 字号物理大小与真机一致。")
    adb(dev, "shell", "wm", "size", f"{px}x{height}")
    if font is not None:
        adb(dev, "shell", "settings", "put", "system", "font_scale", str(font))
        print(f"系统字号 font_scale = {font}")
    print(adb(dev, "shell", "wm", "size").strip())
    print(adb(dev, "shell", "wm", "density").strip())
    print(adb(dev, "shell", "settings", "get", "system", "font_scale").strip())
    print("\n⛔ 验完**立刻** `reset`：这具身体是借的，别的会话/用户会看到它。")
    return 0


def cmd_reset(dev: str) -> int:
    adb(dev, "shell", "wm", "size", "reset")
    adb(dev, "shell", "wm", "density", "reset")
    adb(dev, "shell", "settings", "put", "system", "font_scale", "1.0")
    print("✅ 已还原")
    print(adb(dev, "shell", "wm", "size").strip())
    print(adb(dev, "shell", "wm", "density").strip())
    print("font_scale = " + adb(dev, "shell", "settings", "get", "system", "font_scale").strip())
    return 0


def cmd_shot(dev: str, name: str) -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)
    out = SHOTS / f"{name}.png"
    adb(dev, "shell", "screencap", "-p", "/sdcard/_screensize.png")
    # ⚠️ 不能用 PowerShell 的 `>` 转存（会把 PNG 写坏），必须 adb pull
    p = subprocess.run([ADB, "-s", dev, "pull", "/sdcard/_screensize.png", str(out)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if not out.exists():
        print("❌ 截图失败：" + ((p.stdout or "") + (p.stderr or "")))
        return 1
    print(f"✅ {out}  （{out.stat().st_size} 字节）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["list", "set", "reset", "shot"])
    ap.add_argument("value", nargs="?")
    ap.add_argument("--device", default="5554")
    ap.add_argument("--font", type=float, default=None, help="系统字号（1.0 / 1.3 / 1.5 / 2.0）")
    a = ap.parse_args()
    dev = f"emulator-{a.device}" if not str(a.device).startswith("emulator-") else str(a.device)

    if a.cmd == "list":
        return cmd_list()
    if a.cmd == "set":
        if not a.value:
            print("要给出档位")
            return 2
        return cmd_set(dev, a.value, a.font)
    if a.cmd == "reset":
        return cmd_reset(dev)
    if not a.value:
        print("要给出截图名字")
        return 2
    return cmd_shot(dev, a.value)


if __name__ == "__main__":
    sys.exit(main())
