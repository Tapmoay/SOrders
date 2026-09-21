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
from datetime import datetime
from pathlib import Path

HOST = "8.145.40.22"
SSH_KEY = Path(os.path.expanduser("~")) / ".ssh" / "id_ed25519_sorders"
REMOTE_DIR = "/opt/SOrders/backend/uploads/app"
# 走 80 端口 + IP 直连：80 到处都通，8080 在一些公司网络/运营商侧会被挡；
# 用 IP 而不是域名则是为了不依赖手机上的 DNS。
URL_BASE = "http://8.145.40.22/static/uploads/app"
API_VERSION_URL = "http://8.145.40.22/api/v1/system/app-version"

ROOT = Path(__file__).resolve().parents[2]

#: 打包时要烧进包里的**生产后端地址** —— 必须是 `https`。
#: ⚠️ 2026-09-21 更正：原来的提示写的是 `http://8.145.40.22`，那是 2026-09-19 切 TLS **之前**留下的。
#:    发布包有两道闸都禁明文 —— `res/xml/network_security_config.xml` 是
#:    `cleartextTrafficPermitted="false"`、`SocketManager.connect` 在非 DEBUG 下直接拒绝非 https 的长连接。
#:    所以照那个提示打出来的包**装得上、但每一个请求都失败**（用户看到的是"App 打不开"）。
PROD_API_BASE = "https://8.145.40.22"


def product_version() -> str:
    """产品版本（versionName 的来源）：仓库根 `VERSION` 的第一行。

    为什么读文件而不是在 gradle 里另写一个：`backend/app/config.py::product_version` 读的是同一个文件，
    前端 `package.json` 也对齐它。三处同源，用户报版本时才对得上号。
    """
    f = ROOT / "VERSION"
    if f.is_file():
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                return line.strip()
    return "0.0.0"


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
    # `aapt2 dump badging` 对 `android:debuggable="true"` 的包会多打一行 `application-debuggable`
    # —— 这一行就是"拿到手机的人能不能用 `adb shell run-as` / `adb backup` 直接抽数据"的判据。
    debuggable = "application-debuggable" in out.stdout
    return {"pkg": m.group(1), "versionCode": int(m.group(2)), "versionName": m.group(3),
            "debuggable": debuggable}


def find_apksigner() -> str:
    sdk = os.environ.get("ANDROID_HOME") or r"D:\APPS\sdk"
    bt = Path(sdk) / "build-tools"
    cands = sorted((p / "apksigner.bat" for p in bt.iterdir() if (p / "apksigner.bat").is_file()),
                   key=lambda p: p.parent.name, reverse=True)
    if not cands:
        raise SystemExit("找不到 apksigner.bat，请设置 ANDROID_HOME")
    return str(cands[0])


#: 线上包（= 存量用户手机上那个包）的**签名证书指纹**（SHA-256，去冒号大写）。
#:
#: ⚠️ 它不是"加密材料"，而是**升级能不能装上去**的判据：安卓只允许「同包名 + 同签名 + 更高
#:    versionCode」覆盖安装 —— 指纹一变，所有存量用户都会看到「应用未安装」，只能卸载重装。
#:    所以它必须是发布流程里的一道闸，而不是一句注释（2026-09-19 全项目报告 P0-2/L-8）。
#: 来源（可复算）：
#:    keytool -list -v -keystore %USERPROFILE%\.android\debug.keystore -storepass android -alias androiddebugkey
EXPECTED_CERT_SHA256 = "8AAC1B5778F8DDCFC2613FC9B9574AE8E380F13D59D402B49FEC75ADC259DEE0"


def cert_sha256(apk: Path) -> str:
    """这个 APK 的签名证书 SHA-256（去冒号大写）—— 用来确认"还是原来那把钥匙"。"""
    out = subprocess.run([find_apksigner(), "verify", "--print-certs", str(apk)],
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    m = re.search(r"certificate SHA-256 digest:\s*([0-9a-fA-F:]+)", out.stdout or "")
    if not m:
        raise SystemExit("读不出签名证书指纹（这个包大概率**没签名**，装不上）：\n"
                         + (out.stdout or "") + (out.stderr or ""))
    return m.group(1).replace(":", "").upper()


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
    # ⛔ 默认产物从 **debug** 改成 **release**（2026-09-19 全项目报告 P0-2，high）：
    #    以前这里指向 `phone/debug/app-phone-debug.apk`，于是"发布"这个动作本身就在把
    #    `debuggable=true` + `DEBUG_LOG=true` 的包推给所有用户（生产上跑的一直是它）。
    p = ROOT / "android" / "app" / "build" / "outputs" / "apk" / "phone" / "release" / "app-phone-release.apk"
    if not p.is_file():
        raise SystemExit(
            "没找到手机包，先构建：\n"
            "  gradle -p android assemblePhoneRelease '-PappVersionName=...' '-PappVersionCode=...'\n"
            "找不到：" + str(p))
    return p


# 开发用的后端地址。组进包里就是灾难：真机连不上 10.0.2.2（那是模拟器指代宿主机的别名），
# 而真机上装出来的表现是"App 一片空白/一直在转圈"，跟"更新失败"完全不像同一回事，
# 排查会绕远路。2026-09-15 就差点这样发出去。
DEV_URL_PATTERNS = ("10.0.2.2", "127.0.0.1", "localhost", "192.168.", "172.16.", "172.17.",
                    "172.18.", "172.19.", "172.2", "172.30.", "172.31.", ":8000")


def baked_api_base_url(apk: Path | None = None) -> str:
    """读 AGP 生成的 BuildConfig.java —— 这才是**这个包真正编译进去**的地址。

    为什么不读 android/local.properties：那份文件随时可能被改，
    而包是几分钟前构建的，两者可以不一致。要拦就拦真的那个。

    ⚠️ 必须读**正在发布的那个包**的变体（2026-09-19）：手上同时有 debug 与 release 两份
    `BuildConfig.java` 时，原来按名字排序取第一份 = 取到 `phone/debug` 那份。于是
    「release 包里编译的是开发地址、而 debug 那份恰好写着生产地址」这种组合会被**放行**——
    那正是这道闸要拦的灾难。变体名直接从 APK 路径取（…/apk/phone/release/app-….apk）。

    ⚠️ 2026-09-21 第二次修：`--apk` 指向**仓库之外**的产物时（发布 0.2.2 时为了避开另一个
    会话未提交的改动，我在 `git worktree` 里打的包），原来固定去 `ROOT/android/...` 找，
    读到的是**主检出里那份过期的** BuildConfig → 一个完全正确的真机包被判
    「包里的后端地址是开发地址」而拒绝发布（同一份代码在 `check_phone_apk.py` 里也犯过，
    两边一起修的）。现在：**先看包自己所在的那棵树**，找不到才退回主检出。
    """
    project = ROOT / "android"
    if apk is not None and len(apk.parents) > 6 and (apk.parents[6] / "app").is_dir():
        project = apk.parents[6]
    base = project / "app" / "build" / "generated" / "source" / "buildConfig"
    hits = sorted(base.rglob("BuildConfig.java"))
    if apk is not None:
        want = set(apk.parts[-3:-1])
        hits = [h for h in hits if want <= set(h.parts)] or hits
    phone = [h for h in hits if "phone" in h.parts]
    target = (phone or hits)
    if not target:
        return ""
    m = re.search(r'API_BASE_URL\s*=\s*"([^"]*)"',
                  target[0].read_text(encoding="utf-8", errors="replace"))
    return m.group(1) if m else ""


def today_base_code() -> int:
    """今天第一个包的构建号：`yyyyMMdd * 100 + 1`（与 `android/app/build.gradle.kts` 的缺省值同源）。"""
    return int(datetime.now().strftime("%Y%m%d")) * 100 + 1


def next_code(old_code: int) -> int:
    """该用的下一个构建号 = `max(线上号 + 1, 今天第一个号)`。

    为什么要有它（2026-09-21 用户要求「版本号做一个正规化的处理」）：
    日期式的缺省值**只给到"今天第 1 个包"**，而实际一天会打两三个包 ——
    原来的流程是让发布者自己心算 `-PappVersionCode=2026092102`，算错就撞上下面那道闸，
    而闸门只丢一句"请提高版本号"。这里把它变成**一个能直接照抄的数字**。
    """
    return max(old_code + 1, today_base_code())


def rebuild_hint(code: int, name: str) -> str:
    """打包命令（版本名与版本号都显式给，避免"包里的号"与"打算发的号"不是一回事）。"""
    return (
        f"  gradle -p android assemblePhoneRelease "
        f"'-PappVersionName={name}' '-PappVersionCode={code}' '-PapiBaseUrl={PROD_API_BASE}'\n"
        f"  python _tools/deploy/publish_apk.py --note \"...\""
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apk", type=Path, default=None)
    ap.add_argument("--note", default="")
    ap.add_argument("--version-code", type=int, default=None,
                    help="不传就用包里的 versionCode")
    ap.add_argument("--installed-code", type=int, default=None,
                    help="用户手机上当前那个包的 versionCode（可选，多一道保险）")
    ap.add_argument("--keep", type=int, default=2, help="服务器上保留几个历史包")
    ap.add_argument("--next-code", action="store_true",
                    help="只算「这次该用哪个构建号」并打出完整命令，不读包、不上传")
    ap.add_argument("--dry-run", action="store_true",
                    help="只跑前置检查（后端地址 / versionCode 闸门），不上传不写 version.json")
    args = ap.parse_args()

    # `--next-code`：**打包之前**就要能问（包里那个号是旧的，等它报错才知道要改号就晚了）。
    if args.next_code:
        online = online_version()
        if not online:
            raise SystemExit(
                f"读不到线上 version.json，算不出下一个号（不能瞎猜：猜小了用户装不上）。\n"
                f"      {API_VERSION_URL}")
        old = int(online.get("versionCode") or 0)
        nxt = next_code(old)
        print(f"线上      : versionName={online.get('version') or '(无)'} versionCode={old}")
        print(f"产品版本  : {product_version()}（仓库根 VERSION）")
        print(f"这次用    : versionCode={nxt}")
        print("打包与发布（两条命令照抄）：")
        print(rebuild_hint(nxt, product_version()))
        return 0

    apk = args.apk or default_apk()
    if not apk.is_file():
        raise SystemExit("包不存在：" + str(apk))
    info = badging(apk)
    code = args.version_code or info["versionCode"]
    name = info["versionName"]
    size = apk.stat().st_size
    print(f"本地包 : {apk.name}  {size/1048576:.1f} MB  versionName={name} versionCode={code}")

    # ⓪-a 产物本身的两道硬闸（原来**一条都没有**：`_check_update_flow.py` 33/33 全绿也拦不住
    #      一个 debuggable 的包上线，因为那些检查全在客户端那条链路上）。
    if info["debuggable"]:
        raise SystemExit(
            "中止：这个包是 **debuggable** 的（aapt2 打出 `application-debuggable`）。\n"
            "      装到用户手机上，任何人插一次 USB 就能 `adb shell run-as` 读走会话令牌，\n"
            "      调试日志里还会带登录口令与 JWT。请发 release 变体：\n"
            "  gradle -p android assemblePhoneRelease '-PappVersionName=...' '-PappVersionCode=...'")
    fp = cert_sha256(apk)
    if fp != EXPECTED_CERT_SHA256:
        raise SystemExit(
            f"中止：签名证书指纹与线上不一致。\n      新包 {fp}\n      线上 {EXPECTED_CERT_SHA256}\n"
            "      指纹变了 = 存量用户**装不上**这个更新（安卓要求同包名 + 同签名），\n"
            "      只能让他们卸载重装。确认是有意换钥匙，再改 EXPECTED_CERT_SHA256。")
    print(f"签名   : {fp[:16]}…（与线上一致，存量用户可直接升级）")

    # ⓪ 后端地址必须是生产地址。
    base_url = baked_api_base_url(apk)
    print(f"后端址 : {base_url or '(读不到 BuildConfig，跳过这项检查)'}")
    if base_url:
        bad = [p for p in DEV_URL_PATTERNS if p in base_url]
        if bad:
            raise SystemExit(
                f"中止：这个包的后端地址是开发地址 {base_url}（命中 {', '.join(bad)}）。\n"
                f"      装到真机上会连不上后端，用户看到的是「App 打不开」，不是「更新失败」。\n"
                f"      修法：重新打包时用 -PapiBaseUrl={PROD_API_BASE} 覆盖，例如\n"
                f"        gradle -p android assemblePhoneRelease -PapiBaseUrl={PROD_API_BASE}\n"
                f"      （**不要去改** android/local.properties —— 改了要记得改回来，"
                f"忘了就会让本地调试直接打在生产库上）")

    online = online_version()
    # ⛔ 读不到线上清单 → **停**（2026-09-19 报告 P1-2，fail-open）：
    #    原来这里静默"按没有旧版本处理"，于是两道 versionCode 闸门**同时失效**，
    #    推上去一个不比线上大的包 —— 用户下完只会看到「应用未安装」，
    #    而服务器上 version.json 已经指向它了（所有人一起装不上）。
    if not online:
        raise SystemExit(
            f"中止：读不到线上 version.json，无法确认版本号闸门。\n      {API_VERSION_URL}\n"
            "      读不到时继续发布 = 跳过两道 versionCode 闸门（用户会「应用未安装」）。\n"
            "      确认服务器可达后重试。")
    old_code = int(online.get("versionCode") or 0)
    old_name = online.get("version") or "(无)"
    print(f"线上包 : versionName={old_name} versionCode={old_code or '(version.json 里没写)'}")

    # ②③ 版本号两道闸。安卓安装器只认 versionCode；推一个不比线上大的包，
    #     用户下完只会看到"应用未安装"，而且**没有任何日志能告诉他为什么**。
    if old_code and code <= old_code:
        nxt = next_code(old_code)
        raise SystemExit(
            f"中止：新包 versionCode={code} 不大于线上 {old_code}。\n"
            f"      安卓会拒绝安装（用户下完只看到「应用未安装」，而且没有任何日志说明原因）。\n"
            f"      这次该用的号是 **{nxt}**（= max(线上+1, 今天第 1 个号)）：\n"
            + rebuild_hint(nxt, product_version()))
    if args.installed_code and code <= args.installed_code:
        raise SystemExit(
            f"中止：新包 versionCode={code} 不大于用户手机上的 {args.installed_code}，装不上。\n"
            + rebuild_hint(next_code(max(old_code, args.installed_code)), product_version()))

    # 包名带上构建号：**产品版本语义化之后（0.2.0 这种）文件名会重复**，
    # 同日第二个包会覆盖线上第一个包 —— 而 version.json 里 url 不变，看起来"发了新版"，
    # 实际拿到的是被覆盖后的新文件、旧包没了，--keep 也留不住历史。
    remote_apk = f"{REMOTE_DIR}/sorders-{name}-{code}.apk"
    if args.dry_run:
        print(f"[dry-run] 前置检查都过了，本来会上传 {apk.name} → {remote_apk}")
        print(f"[dry-run] 本来会写 version.json：version={name} versionCode={code} "
              f"url={URL_BASE}/sorders-{name}-{code}.apk")
        return 0

    print(f"上传中 : {apk.name} → {remote_apk}")
    scp(apk, remote_apk)
    # 同时留一份**最新包的短链**（`http://8.145.40.22/apk` → `sorders-latest.apk`）。
    # 为什么要它（2026-09-19）：服务端开始拒绝明文登录之后，老版本 App 的用户会卡在登录页，
    # 而"检查更新"在登录之后的页面里、那个页面他们进不去 —— 拒绝报文里只能给一条能念出来的短链。
    ssh(f"cp -f {remote_apk} {REMOTE_DIR}/sorders-latest.apk")
    print(f"短链   : {URL_BASE.rsplit('/static', 1)[0]}/apk → sorders-latest.apk")

    ver = {
        "version": name,
        "versionCode": code,
        "url": f"{URL_BASE}/sorders-{name}-{code}.apk",
        "size": size,
        "note": args.note or "",
    }
    payload = json.dumps(ver, ensure_ascii=False)
    ssh(f"cat > {REMOTE_DIR}/version.json.tmp <<'JSONEOF'\n{payload}\nJSONEOF")
    ssh(f"mv {REMOTE_DIR}/version.json.tmp {REMOTE_DIR}/version.json")
    # 顺手清历史包，别把 40G 的盘塞满（`sorders-latest.apk` 不匹配 `sorders-<版本>.apk` 的清理口径？
    # 它匹配 `sorders-*.apk` —— 所以**必须显式排除**，否则"最新包"会被当成最旧的那个删掉）
    ssh(f"ls -1t {REMOTE_DIR}/sorders-*.apk | grep -v 'sorders-latest.apk$' | tail -n +{args.keep + 1} | xargs -r rm -f")
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
