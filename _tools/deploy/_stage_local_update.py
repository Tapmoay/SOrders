#!/usr/bin/env python3
"""在本地造一个「假的新版本」，用来在模拟器上把应用内更新整条链走一遍。

为什么要这个：应用内更新是**只有真跑一遍才知道对不对**的东西——
单元测试测不到 FileProvider 的根目录配错、测不到安卓的「安装未知应用」开关、
测不到系统安装器到底有没有被拉起来。2026-09-15 用户报的
「下载完成之后并没有更新」，就是这三件事里的第一件，纯看代码很难确信。

它做的事：
  ① 把一个 APK 放到 backend/uploads/app/，作为"新版本"的下载源；
  ② 写 backend/uploads/app/version.json，versionCode 故意比本机大；
  ③ 打印模拟器该走的操作路径。

⚠️ 只在本地开发环境用。version.json 是会被后端直接读走并发给客户端的，
   别把这里的假数据留在生产（生产用 _tools/deploy/publish_apk.py）。

用法：
  python _tools/deploy/_stage_local_update.py --apk <要当新版本的包> \
      --version 1.0.0.20260918 --version-code 2026091801
  python _tools/deploy/_stage_local_update.py --clear      # 清掉，恢复正常
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / "backend" / "uploads" / "app"
APK_NAME = "sorders-test-new.apk"
# 模拟器访问宿主机固定是 10.0.2.2
URL = f"http://10.0.2.2:8000/static/uploads/app/{APK_NAME}"


def clear() -> None:
    for n in (APK_NAME, "version.json"):
        p = DEST / n
        if p.is_file():
            p.unlink()
            print("已删除", p)
    print("本地假更新已清掉（后端会重新返回 version=null，App 显示「暂未发布新版本」）")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apk", type=Path)
    ap.add_argument("--version", default="")
    ap.add_argument("--version-code", type=int, default=0)
    ap.add_argument("--note", default="本地联调用的假更新包（模拟器专用，不要推到生产）")
    ap.add_argument("--clear", action="store_true")
    args = ap.parse_args()

    if args.clear:
        clear()
        return 0
    if not args.apk or not args.version or not args.version_code:
        raise SystemExit("需要 --apk / --version / --version-code（或 --clear）")
    if not args.apk.is_file():
        raise SystemExit("包不存在：" + str(args.apk))

    DEST.mkdir(parents=True, exist_ok=True)
    shutil.copy(args.apk, DEST / APK_NAME)
    ver = {
        "version": args.version,
        "versionCode": args.version_code,
        "url": URL,
        "size": (DEST / APK_NAME).stat().st_size,
        "note": args.note,
    }
    (DEST / "version.json").write_text(
        json.dumps(ver, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("已布置假更新：")
    print("  version     =", args.version)
    print("  versionCode =", args.version_code, "（App 里的 versionCode 必须比它小）")
    print("  url         =", URL)
    print()
    print("模拟器上验证步骤：")
    print("  1) adb shell am start -n com.tapmoay.sorders/.MainActivity")
    print("  2) 底部「我的」→「检查更新」→ 应弹「发现新版本 v" + args.version + "」")
    print("  3) 点「下载并更新」→ 看系统安装器是否被拉起、装完版本号是否变了")
    print("  4) 想验证「安装未知应用」那条分支：")
    print("     adb shell appops set com.tapmoay.sorders REQUEST_INSTALL_PACKAGES deny")
    print("     ——此时点「下载并更新」应该弹 App 自己的「还差一步：允许安装应用」，且不开始下载")
    print()
    print("验完记得： python _tools/deploy/_stage_local_update.py --clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
