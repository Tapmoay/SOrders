#!/usr/bin/env python3
"""把一个 Android 包推送到生产服务器，并写好 version.json（App「检查更新」读的就是它）。

为什么要有这个脚本（2026-09-15）：
  「推送」以前是每次手敲命令，于是踩了这个坑——
  线上 version.json 里的包是用 System.currentTimeMillis()/1000 兜底的 versionCode
  （1789426316），而本地打包一直显式传日期式（2026091501）。两套量纲混着用，
  后打的包 versionCode 有可能反而更小，安卓就**直接拒绝安装**，
  对外表现是「下载完成之后并没有更新」。手敲命令的流程挡不住这种错，
  所以把「上传 + 写 version.json + 校验」固化成一个带前置检查的脚本。

它做的检查（任一条不过就中止，不会把坏版本推上去）：
  ① 包能解析出版本号；
  ② 新包 versionCode > 线上 versionCode（否则安卓不会装，推了也白推）；
  ③ 可选 --installed-code：再比一次用户手机上那个包，防止"比线上新、比用户旧"；
  ④ 推完再回读一次 version.json 和 APK 响应头，确认真的生效。

用法：
  python _tools/deploy/publish_apk.py --note "修好应用内更新"
  python _tools/deploy/publish_apk.py --apk <path> --version-code 2026091601
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

HOST = "8.145.40.22"
SSH_KEY = Path(os.path.expanduser("~")) / ".ssh" / "id_ed25519_sorders"
REMOTE_DIR = "/opt/SOrders/backend/uploads/app"
# 走 80 端口 + IP 直连：80 到处都通，8080 在一些公司网络/运营商侧会被挡；
# 用 IP 而不是域名则是为了不依赖手机上的 DNS。
URL_BASE = "http://8.145.40.22/static/uploads/app"
API_VERSION_URL = "http://8.145.40.22/api/v1/system/app-version"

ROOT = Path(__file__).resolve().parents[2]


def find_aapt2() -> str:
    sdk = os.environ.get("ANDROID_HOME") or r"D:\APPS\sdk"
    bt = Path(sdk) / "build-tools"
    cands = sorted((p / "aapt2.exe" for p in bt.iterdir() if (p / "aapt2.exe").is_file()),
                   key=lambda p: p.parent.name, reverse=True)
    if not cands:
        raise SystemExit("找不到 aapt2.exe，请设置 ANDROID_HOME")
    return str(cands[0])


def badging(apk: Path) -> dict:
    out = subprocess.run([find_aapt2(), "dump", "badging", str(apk)],
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    if out.returncode != 0:
        raise SystemExit("aapt2 dump badging 失败：\n" + (out.stderr or ""))
    m = re.search(r"package: name='([^']+)' versionCode='(\d+)' versionName='([^']*)'", out.stdout)
    if not m:
        raise SystemExit("解析不出包信息，确认这是个 APK：" + str(apk))
    return {"pkg": m.group(1), "versionCode": int(m.group(2)), "versionName": m.group(3)}


def ssh(*cmd: str, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(
        ["ssh", "-i", str(SSH_KEY), "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
         f"root@{HOST}", " ".join(cmd)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise SystemExit("远程命令失败：" + " ".join(cmd) + "\n" + (r.stderr or ""))
    return r


def scp(local: Path, remote: str) -> None:
    r = subprocess.run(
        ["scp", "-i", str(SSH_KEY), "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
         str(local), f"root@{HOST}:{remote}"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise SystemExit("scp 失败：\n" + (r.stderr or ""))


def online_version() -> dict:
    try:
        with urllib.request.urlopen(API_VERSION_URL, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        print(f"  ! 读不到线上 version.json（{e}），按「没有旧版本」处理")
        return {}


def default_apk() -> Path:
    p = ROOT / "android" / "app" / "build" / "outputs" / "apk" / "phone" / "debug" / "app-phone-debug.apk"
    if not p.is_file():
        raise SystemExit(
            "没找到手机包，先构建：\n"
            "  gradle -p android assemblePhoneDebug '-PappVersionName=...' '-PappVersionCode=...'\n"
            "找不到：" + str(p))
    return p


# 开发用的后端地址。组进包里就是灾难：真机连不上 10.0.2.2（那是模拟器指代宿主机的别名），
# 而真机上装出来的表现是"App 一片空白/一直在转圈"，跟"更新失败"完全不像同一回事，
# 排查会绕远路。2026-09-15 就差点这样发出去。
DEV_URL_PATTERNS = ("10.0.2.2", "127.0.0.1", "localhost", "192.168.", "172.16.", "172.17.",
                    "172.18.", "172.19.", "172.2", "172.30.", "172.31.", ":8000")


def baked_api_base_url() -> str:
    """读 AGP 生成的 BuildConfig.java —— 这才是**这个包真正编译进去**的地址。

    为什么不读 android/local.properties：那份文件随时可能被改，
    而包是几分钟前构建的，两者可以不一致。要拦就拦真的那个。
    """
    base = ROOT / "android" / "app" / "build" / "generated" / "source" / "buildConfig"
    hits = sorted(base.rglob("BuildConfig.java"))
    phone = [h for h in hits if "phone" in h.parts]
    target = (phone or hits)
    if not target:
        return ""
    m = re.search(r'API_BASE_URL\s*=\s*"([^"]*)"',
                  target[0].read_text(encoding="utf-8", errors="replace"))
    return m.group(1) if m else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apk", type=Path, default=None)
    ap.add_argument("--note", default="")
    ap.add_argument("--version-code", type=int, default=None,
                    help="不传就用包里的 versionCode")
    ap.add_argument("--installed-code", type=int, default=None,
                    help="用户手机上当前那个包的 versionCode（可选，多一道保险）")
    ap.add_argument("--keep", type=int, default=2, help="服务器上保留几个历史包")
    ap.add_argument("--dry-run", action="store_true",
                    help="只跑前置检查（后端地址 / versionCode 闸门），不上传不写 version.json")
    args = ap.parse_args()

    apk = args.apk or default_apk()
    if not apk.is_file():
        raise SystemExit("包不存在：" + str(apk))
    info = badging(apk)
    code = args.version_code or info["versionCode"]
    name = info["versionName"]
    size = apk.stat().st_size
    print(f"本地包 : {apk.name}  {size/1048576:.1f} MB  versionName={name} versionCode={code}")

    # ⓪ 后端地址必须是生产地址。
    base_url = baked_api_base_url()
    print(f"后端址 : {base_url or '(读不到 BuildConfig，跳过这项检查)'}")
    if base_url:
        bad = [p for p in DEV_URL_PATTERNS if p in base_url]
        if bad:
            raise SystemExit(
                f"中止：这个包的后端地址是开发地址 {base_url}（命中 {', '.join(bad)}）。\n"
                f"      装到真机上会连不上后端，用户看到的是「App 打不开」，不是「更新失败」。\n"
                f"      修法：把 android/local.properties 的 api_base_url 改成生产地址，"
                f"重新 assemblePhoneDebug 再推。")

    online = online_version()
    old_code = int(online.get("versionCode") or 0)
    old_name = online.get("version") or "(无)"
    print(f"线上包 : versionName={old_name} versionCode={old_code or '(version.json 里没写)'}")

    # ②③ 版本号两道闸。安卓安装器只认 versionCode；推一个不比线上大的包，
    #     用户下完只会看到"应用未安装"，而且**没有任何日志能告诉他为什么**。
    if old_code and code <= old_code:
        raise SystemExit(
            f"中止：新包 versionCode={code} 不大于线上 {old_code}。\n"
            f"      安卓会拒绝安装。请提高版本号后重新打包（-PappVersionCode=...）。")
    if args.installed_code and code <= args.installed_code:
        raise SystemExit(
            f"中止：新包 versionCode={code} 不大于用户手机上的 {args.installed_code}，装不上。")

    remote_apk = f"{REMOTE_DIR}/sorders-{name}.apk"
    if args.dry_run:
        print(f"[dry-run] 前置检查都过了，本来会上传 {apk.name} → {remote_apk}")
        print(f"[dry-run] 本来会写 version.json：version={name} versionCode={code} "
              f"url={URL_BASE}/sorders-{name}.apk")
        return 0

    print(f"上传中 : {apk.name} → {remote_apk}")
    scp(apk, remote_apk)

    ver = {
        "version": name,
        "versionCode": code,
        "url": f"{URL_BASE}/sorders-{name}.apk",
        "size": size,
        "note": args.note or "",
    }
    payload = json.dumps(ver, ensure_ascii=False)
    ssh(f"cat > {REMOTE_DIR}/version.json.tmp <<'JSONEOF'\n{payload}\nJSONEOF")
    ssh(f"mv {REMOTE_DIR}/version.json.tmp {REMOTE_DIR}/version.json")
    # 顺手清历史包，别把 40G 的盘塞满
    ssh(f"ls -1t {REMOTE_DIR}/sorders-*.apk | tail -n +{args.keep + 1} | xargs -r rm -f")
    print("已写入 : version.json")

    # ④ 回读验证。不验证的发布等于没发布——线上到底发生效只有这里能证明。
    back = online_version()
    ok_code = int(back.get("versionCode") or 0) == code
    print(f"回读   : version={back.get('version')} versionCode={back.get('versionCode')} "
          f"{'OK' if ok_code else '!! 不一致'}")
    if not ok_code:
        return 2

    req = urllib.request.Request(ver["url"], headers={"Range": "bytes=0-1023"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            ct = resp.headers.get("Content-Type")
            cr = resp.headers.get("Content-Range")
            print(f"探包   : HTTP {resp.status}  Content-Type={ct}  Content-Range={cr}")
            if resp.status != 206 or "android.package-archive" not in (ct or ""):
                print("  ! 期望 206 + application/vnd.android.package-archive；"
                      "浏览器手动下载可能因此表现异常")
    except Exception as e:  # noqa: BLE001
        print("  ! 回读安装包失败：" + str(e))
    print("完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
