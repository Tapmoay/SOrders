"""打印模拟器 UI 层级里的可点/可读节点（含真实 bounds），用于精确定位点击坐标。

用法：
  adb shell uiautomator dump /sdcard/ui.xml
  adb pull /sdcard/ui.xml _emu_ui.xml
  python _tools/ai/_ui_dump.py [_emu_ui.xml] [关键字...]
"""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402


def center(bounds: str) -> str:
    try:
        a, b = bounds.split("][")
        x1, y1 = (int(v) for v in a.strip("[]").split(","))
        x2, y2 = (int(v) for v in b.strip("[]").split(","))
        return f"({(x1 + x2) // 2},{(y1 + y2) // 2})"
    except Exception:  # noqa: BLE001
        return "?"


def main() -> int:
    args = sys.argv[1:]
    path = Path(args[0]) if args and args[0].endswith(".xml") else repo_root() / "_emu_ui.xml"
    kws = [a for a in args if not a.endswith(".xml")]
    if not path.exists():
        print(f"找不到 {path}")
        return 1

    root = ET.parse(path).getroot()
    for n in root.iter("node"):
        txt = (n.get("text") or "").strip()
        desc = (n.get("content-desc") or "").strip()
        cls = (n.get("class") or "").split(".")[-1]
        if not (txt or desc):
            continue
        if kws and not any(k in txt or k in desc for k in kws):
            continue
        flags = []
        if n.get("clickable") == "true":
            flags.append("CLICK")
        if n.get("scrollable") == "true":
            flags.append("SCROLL")
        print(f"  [{cls:<14}] {txt or desc!r:<26} {' '.join(flags):<12} "
              f"bounds={n.get('bounds')} center={center(n.get('bounds') or '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
