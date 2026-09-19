"""在当前页面上「找到某个文字就点它」——通过小步慢滑 + 每步重新 dump。

为什么需要：AI 设置页很长（模型配置 + 工具开关 + 习惯 + 记忆），而「保存」按钮
在最下面一串列表之前；`input swipe` 距离一大就变成 fling，一次能滑过好几屏，
坐标写死必然点空。这里改成"慢滑一小步 → 找一次"，找到才点。

用法：
    python _tools/notify/_scroll_tap.py 保存            # 往下找
    python _tools/notify/_scroll_tap.py 保存 --up       # 往上找
"""
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _ui import adb, center, nodes  # noqa: E402


def find(label: str):
    for n in nodes():
        if n["text"] == label:
            return n
    return None


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    label = sys.argv[1]
    up = "--up" in sys.argv
    x0 = 1020
    # ⚠️ 方向别搞反：手指**向下**划（900→1150）内容才往上走 = 看更前面的内容。
    y0, y1 = (900, 1050) if up else (1050, 900)

    for i in range(24):
        n = find(label)
        if n:
            cx, cy = center(n["box"])
            adb("shell", "input", "tap", str(cx), str(cy))
            print(f"✅ 第 {i} 步找到「{label}」→ 点了 {cx},{cy}")
            return 0
        # 慢滑一小步：150px / 1200ms ≈ 125px/s，速度低到不会触发 fling。
        # 之前用 300px/800ms 会滑过头——一次能翻 700px+，目标按钮整块被跳过。
        adb("shell", "input", "swipe", str(x0), str(y0), str(x0), str(y1), "1200")
        time.sleep(0.5)
    print(f"❌ 滑了 24 步也没找到「{label}」")
    return 1


if __name__ == "__main__":
    sys.exit(main())
