"""按**文字**操作模拟器（而不是硬编码坐标）。

为什么需要：验证司机端提醒要反复点「消息提醒」「试听一声」「开关」，
而这一页的布局会随设置状态变化（语音关了就没有"念几遍"那一段），
写死 y 坐标的脚本会**点到别的行上**，然后你会得到一个看起来像 bug 的假结果。
文字定位不会。

用法：
    python _tools/notify/_ui.py texts                     # 打印当前页所有文字（带坐标）
    python _tools/notify/_ui.py tap 试听一声               # 点这个文字所在的位置
    python _tools/notify/_ui.py taprow 新单语音提醒        # 点这一行最右侧的开关
    python _tools/notify/_ui.py shot out.png              # 截图并拉回本地
    python _tools/notify/_ui.py logs                      # 打印 SOrdersAlert 日志
"""
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ADB = r"D:\APPS\sdk\platform-tools\adb.exe"
ROOT = Path(__file__).resolve().parents[2]


def adb(*args: str, timeout: int = 30) -> str:
    r = subprocess.run([ADB, *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    return (r.stdout or "") + (r.stderr or "")


NODE = re.compile(r'<node[^>]*>')


def nodes() -> list[dict]:
    adb("shell", "uiautomator", "dump", "/sdcard/_ui.xml")
    xml = adb("shell", "cat", "/sdcard/_ui.xml")
    out = []
    for tag in NODE.findall(xml):
        text = re.search(r'text="([^"]*)"', tag)
        cls = re.search(r'class="([^"]*)"', tag)
        desc = re.search(r'content-desc="([^"]*)"', tag)
        bounds = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
        if not bounds:
            continue
        x1, y1, x2, y2 = (int(bounds.group(i)) for i in range(1, 5))
        out.append({
            "text": text.group(1) if text else "",
            # 顶栏那些按钮**没有文字、只有 content-desc**（返回/历史/新对话/设置），
            # 只按 text 找会"点了没反应"——这种静默失败最费时间。
            "desc": desc.group(1) if desc else "",
            "cls": cls.group(1) if cls else "",
            "box": (x1, y1, x2, y2),
            "cy": (y1 + y2) // 2,
        })
    return out


def center(box):
    x1, y1, x2, y2 = box
    return (x1 + x2) // 2, (y1 + y2) // 2


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    cmd = sys.argv[1]

    if cmd == "texts":
        for n in nodes():
            if n["text"]:
                print(f"{n['text']}   {n['box']}")
        return 0

    if cmd == "tap":
        label = " ".join(sys.argv[2:])
        for n in nodes():
            if n["text"] == label:
                x, y = center(n["box"])
                adb("shell", "input", "tap", str(x), str(y))
                print(f"点了「{label}」 @ {x},{y}")
                return 0
        print(f"❌ 找不到「{label}」")
        return 1

    if cmd == "tapdesc":
        # 顶栏图标按钮只有 content-desc（返回/历史/新对话/设置）
        label = " ".join(sys.argv[2:])
        for n in nodes():
            if n["desc"] == label:
                x, y = center(n["box"])
                adb("shell", "input", "tap", str(x), str(y))
                print(f"点了 [{label}] @ {x},{y}")
                return 0
        print(f"❌ 找不到 content-desc「{label}」")
        return 1

    if cmd == "taprow":
        # 点这一行的**开关**：先找真正的 android.widget.Switch（纵向离这一行最近的那个），
        # 找不到才退回"同一行里 x 最大的控件"。
        # ⚠️ 退回分支会点到整行的容器，而整行也是可点的（点哪都会切换开关），
        #    于是"看起来点对了、其实切换了状态却没打日志"——第一次就是这么被骗的。
        label = " ".join(sys.argv[2:])
        rows = nodes()
        anchor = next((n for n in rows if n["text"] == label), None)
        if anchor is None:
            print(f"❌ 找不到「{label}」")
            return 1
        switches = [n for n in rows if n["cls"] == "android.widget.Switch"]
        if switches:
            target = min(switches, key=lambda n: abs(n["cy"] - anchor["cy"]))
            x, y = center(target["box"])
            adb("shell", "input", "tap", str(x), str(y))
            print(f"点了「{label}」的开关 @ {x},{y}")
            return 0
        y = anchor["cy"]
        same_row = [n for n in rows if n["box"][1] - 20 <= y <= n["box"][3] + 20 and n["box"][2] > anchor["box"][2]]
        if not same_row:
            print(f"❌ 「{label}」这一行右侧没有可点的控件")
            return 1
        target = max(same_row, key=lambda n: n["box"][2])
        x, y2 = center(target["box"])
        adb("shell", "input", "tap", str(x), str(y2))
        print(f"点了「{label}」行右侧的 {target['cls'].split('.')[-1] or '控件'} @ {x},{y2}")
        return 0

    if cmd == "shot":
        name = sys.argv[2] if len(sys.argv) > 2 else "shot.png"
        adb("shell", "screencap", "-p", "/sdcard/_shot.png")
        dest = ROOT / name if not Path(name).is_absolute() else Path(name)
        adb("pull", "/sdcard/_shot.png", str(dest))
        print(dest)
        return 0

    if cmd == "logs":
        print(adb("logcat", "-d", "-s", "SOrdersAlert:I", "SOrdersSock:I"))
        return 0

    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
