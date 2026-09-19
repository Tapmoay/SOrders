"""数一遍安卓单测结果（替代 PowerShell 手工解析 XML，避免"部分文件解析失败还打印出总数"）。

用法：python _tools/qa/_android_test_count.py
"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    dirs = sorted((ROOT / "android/app/build/test-results").glob("test*UnitTest"))
    if not dirs:
        print("✗ 找不到 test-results 目录（先跑 gradle :app:testEmuDebugUnitTest）")
        return 1
    total = fails = errs = skipped = 0
    for d in dirs:
        dt = df = de = ds = 0
        files = 0
        newest = ""
        for f in sorted(d.glob("*.xml")):
            files += 1
            try:
                root = ET.parse(f).getroot()
            except ET.ParseError as e:
                print(f"✗ 解析失败 {f.name}: {e}")
                return 1
            newest = max(newest, f.stat().st_mtime.__str__()[:10] and __import__('datetime').datetime.fromtimestamp(f.stat().st_mtime).strftime('%m-%d %H:%M'))
            suites = [root] if root.tag == "testsuite" else list(root)
            for s in suites:
                dt += int(s.get("tests", 0))
                df += int(s.get("failures", 0))
                de += int(s.get("errors", 0))
                ds += int(s.get("skipped", 0))
        print(f"{d.relative_to(ROOT)}: {files} 个类 / tests={dt} failures={df} errors={de} skipped={ds}"
              f" / 最新报告 {newest}")
        total += dt; fails += df; errs += de; skipped += ds
    print(f"合计 tests={total} failures={fails} errors={errs} skipped={skipped}")
    if fails or errs:
        print("⚠️ 有失败：先确认这是**真失败**还是反向验证注入留下的报告"
              "（`_reverse_verify_*.py` 会故意弄坏代码再跑单测，跑完恢复源码但**报告文件不会删**）。"
              "要真数就删掉 test-results 目录重跑一次。")
    return 2 if (fails or errs) else 0


if __name__ == "__main__":
    sys.exit(main())
