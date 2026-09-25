#!/usr/bin/env python3
"""反向验证 `_tools/deploy/_check_update_flow.py` 真的抓得住那几类错误。

## 为什么这条链路特别需要反向验证
应用内更新是**跨 5 个地方**的一条链（FileProvider 根目录 / ProfileViewModel 的下载与安装器 /
gradle 的 versionCode 与 ABI / 后端的 .apk Content-Type / 发布脚本的版本号闸门），
任何一处改错的表现都是「**下载完成了但什么都没发生**」，而且没有任何报错 ——
用户只会说"下载完没更新"。所以这些不变量是**唯一**的守卫，它们必须被证明真的会红。

## 五种破坏（每一种都是现实中真会发生的那种改法）
| # | 注入 | 期望 |
| --- | --- | --- |
| ① | 下载不再发 `Range` 头（断点续传没了） | 红：下载带断点续传 |
| ② | phone flavor 只带一个 ABI | 红：只带 arm64-v8a / armeabi-v7a |
| ③ | file_paths.xml 的 cache-path 不再覆盖 APK 落盘目录 | 红：被 cache-path 覆盖 |
| ④ | 发布脚本的 `next_code` 改名（算号能力没了） | 红：该用哪个构建号 |
| ⑤ | 上传文件名去掉构建号（同日第二个包覆盖第一个） | 红：上传目标与 version.json 同一份 |
| ⑥ | 只让 version.json 的 url 漂移（上传名不变）→ 用户拿到 404 | 红：同上 |

⚠️ 与仓库里其它 `_reverse_verify_*.py` 同一套纪律：按**字节**备份/还原、跑完逐文件核对、
⛔ 全程不碰 `git checkout --`。

用法：python _tools/deploy/_reverse_verify_update_flow.py
      python _tools/deploy/_reverse_verify_update_flow.py --list
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import lock_reverse_verify, unlock_reverse_verify  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/deploy/_check_update_flow.py"
VM = "android/app/src/main/java/com/tapmoay/sorders/ui/profile/ProfileViewModel.kt"
GRADLE = "android/app/build.gradle.kts"
PATHS_XML = "android/app/src/main/res/xml/file_paths.xml"
PUBLISH = "_tools/deploy/publish_apk.py"

CASES: list[tuple[str, str, str, str, str]] = [
    (
        "① 下载不再发 Range 头（断点续传没了 → 断网重下 40MB）",
        VM,
        '.apply { if (done > 0) header("Range", "bytes=$done-") }',
        ".apply { if (done > 0) { /* 注入：不再发 Range */ } }",
        "断点续传",
    ),
    (
        "② phone flavor 只带一个 ABI（老机器装不上，而日志里看不出来）",
        GRADLE,
        'ndk { abiFilters += listOf("arm64-v8a", "armeabi-v7a") }',
        'ndk { abiFilters += listOf("arm64-v8a") }',
        "arm64-v8a / armeabi-v7a",
    ),
    (
        "③ file_paths.xml 不再覆盖 APK 落盘目录（进度 100% 后毫无反应）",
        PATHS_XML,
        '<cache-path name="updates" path="updates/" />',
        '<cache-path name="updates" path="downloads/" />',
        "被 file_paths.xml 的某个 cache-path 覆盖",
    ),
    (
        "④ 发布脚本的 next_code 改名（回到「让发布者自己心算号」）",
        PUBLISH,
        "def next_code(old_code: int) -> int:",
        "def next_code_v2(old_code: int) -> int:",
        "该用哪个构建号",
    ),
    (
        "⑤ 上传文件名去掉构建号（同一天第二个包覆盖第一个）",
        PUBLISH,
        'apk_name = f"sorders-{name}-{code}.apk"',
        'apk_name = f"sorders-{name}.apk"',
        "上传目标与 version.json",
    ),
    (
        "⑥ 只让 version.json 的 url 漂移（上传名不变）—— 用户检查更新会拿到 404",
        PUBLISH,
        '"url": f"{URL_BASE}/{apk_name}",',
        '"url": f"{URL_BASE}/sorders-{name}-{code}.apk",',
        "上传目标与 version.json",
    ),
]

CRLF = chr(13) + chr(10)


class Sandbox:
    """按**字节**记账的注入沙箱。"""

    def __init__(self) -> None:
        self.saved: dict[Path, bytes] = {}

    def apply(self, rel: str, old: str, new: str) -> None:
        p = ROOT / rel
        if not p.exists():
            raise ValueError("找不到 " + rel)
        self.saved.setdefault(p, p.read_bytes())
        raw = p.read_bytes()
        crlf = CRLF.encode("utf-8") in raw
        text = raw.decode("utf-8")
        if crlf:
            text = text.replace(CRLF, chr(10))
        if text.count(old) != 1:
            raise ValueError(rel + " 里锚点出现 " + str(text.count(old)) + " 次（要恰好一次）")
        text = text.replace(old, new, 1)
        p.write_bytes((text.replace(chr(10), CRLF) if crlf else text).encode("utf-8"))

    def restore(self) -> None:
        for p, raw in self.saved.items():
            p.write_bytes(raw)

    def dirty(self) -> list[str]:
        return [str(p.relative_to(ROOT)) for p, raw in self.saved.items() if p.read_bytes() != raw]


def run_check() -> tuple[int, str]:
    proc = subprocess.run([sys.executable, str(CHECK)], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=str(ROOT))
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        for i, (name, rel, _o, _n, want) in enumerate(CASES, 1):
            print(f"{i}. {name}\n      {rel}   ← 期望被「{want}」抓到")
        return 0

    bad = 0
    sb = Sandbox()
    lock_reverse_verify()
    try:
        code, out = run_check()
        if code != 0:
            print("❌ 前提不成立：源码完好时这条红线就没过")
            print(out[-1500:])
            return 1
        last = [ln for ln in out.splitlines() if ln.strip()][-1]
        print("✅ 前提：源码完好时红线是绿的 —— " + last.strip())
        for label, rel, old, new, want in CASES:
            sb.restore()
            try:
                sb.apply(rel, old, new)
                code, out = run_check()
            except ValueError as exc:
                print("  [SKIP] " + label + " —— " + str(exc))
                bad += 1
                continue
            finally:
                sb.restore()
            hit = code != 0 and want in out
            if hit:
                print("  [OK] " + label + " → 红线报红并命中「" + want + "」")
            else:
                bad += 1
                why = "红线居然还是绿的" if code == 0 else "退出了，但没报出「" + want + "」"
                print("  [MISS] " + label + " → " + why)
                for ln in [x.strip() for x in out.splitlines() if x.strip().startswith("   ✗")][:5]:
                    print("       红线实际报的：" + ln)
        sb.restore()
        code, out = run_check()
        ok = code == 0
        print("  [OK] 还原后红线全绿" if ok else "  [MISS] 还原后红线没恢复")
        bad += 0 if ok else 1
    finally:
        sb.restore()
        unlock_reverse_verify()

    dirty = sb.dirty()
    if dirty:
        bad += 1
        print("⛔ 跑完没逐字节还原：" + "、".join(dirty))
    total = len(CASES) + 1
    print()
    if bad:
        print(f"❌ {bad}/{total} 条不成立")
        return 1
    print(f"✅ {total}/{total} 全部成立：更新链路上这五类断点在编译期就会被拦住")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())