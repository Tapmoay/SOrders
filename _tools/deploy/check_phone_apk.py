"""发真机包之前，检查「这个 APK 到底连哪个后端」。

### 为什么必须有这一步
`android/local.properties` 里的 `api_base_url` 平时是**模拟器地址**（`http://10.0.2.2:8000`），
而 `ApiEndpoint` 的规则是：**只要 BuildConfig 里是 10.0.2.2 就直接用、连探测都不探测**
（见 core/ApiEndpoint.kt 第一行分支）。也就是说——**忘了改地址打出来的真机包，
装到手机上会连一个根本不存在的主机**，表现是"登录一直转圈"，
而包本身能装、能开、看不出哪里不对。2026-09-17 差点就这么交出去了。

### 判据取哪里
取**编译时真正用的那份配置**，而不是"dex 里有没有出现过 10.0.2.2"：
后者会误报——`ApiEndpoint` 里本来就有一条模拟器兜底常量
（`else -> "http://10.0.2.2:8000"`，真机上 `isEmulator()` 为 false，永远走不到），
把它当"打进包里的地址"会让人去改一条**本来就对**的代码。

所以查三样：
1. `android/local.properties` 的 `api_base_url`（下次构建会用它）；
2. 生成的 `BuildConfig.java` 里 `API_BASE_URL`（这次构建真的用了它）；
3. APK 比那份 BuildConfig 新（证明这个包就是它编出来的）+ 含 arm64-v8a。

用法：
  python _tools/deploy/check_phone_apk.py                       # 默认查 outputs/apk/phone/debug
  python _tools/deploy/check_phone_apk.py --apk <路径>
退出码 0 = 可以发；非 0 = 别发（并打印怎么改）。
"""
import argparse
import re
import subprocess
import sys
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
ROOT = Path(__file__).resolve().parents[2]
SDK = Path(r"D:\APPS\sdk")
LOCAL_PROPS = ROOT / "android/local.properties"

# 打进真机包就是错的地址（模拟器专用）
EMULATOR_HOSTS = ("http://10.0.2.2", "http://localhost", "http://127.0.0.1")
#: 打包时该烧进包里的生产地址 —— **必须 https**。
#: ⚠️ 2026-09-21 更正：这里原来是 `http://8.145.40.22`（2026-09-19 切 TLS 之前留下的），
#:    而发布包禁明文（network_security_config 的 cleartextTrafficPermitted=false +
#:    SocketManager 非 DEBUG 下拒绝非 https 长连接）→ 照它打出来的包「装得上但用不了」。
PROD_HINT = "https://8.145.40.22"


def aapt2() -> Path:
    bt = sorted((p for p in (SDK / "build-tools").iterdir() if (p / "aapt2.exe").is_file()),
                key=lambda p: p.name, reverse=True)
    if not bt:
        raise SystemExit("找不到 aapt2.exe（设 ANDROID_HOME 或改脚本里的 SDK 路径）")
    return bt[0] / "aapt2.exe"


def prop(name: str) -> str:
    if not LOCAL_PROPS.is_file():
        return ""
    for line in LOCAL_PROPS.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip()
    return ""


def variant_of(apk: Path) -> tuple[str, str] | None:
    """从产物路径推变体：`.../outputs/apk/<flavor>/<build_type>/xxx.apk`。

    ⚠️ 2026-09-21 修：这里原来**写死**读 `phone/debug` 的 BuildConfig，于是 `--apk` 指向
    `phone/release` 时，它会拿 debug 变体的 `http://10.0.2.2:8000` 去判 release 包 →
    **一个完全正确的真机包被判「连的是模拟器地址，重打」**，紧接着那句"dex 里找不到
    10.0.2.2"又自相矛盾（因为它反过来是对的）。发布闸门上的假红最贵：下一个人会把判据改松。
    """
    parts = list(apk.parts)
    if "apk" not in parts:
        return None
    i = len(parts) - 1 - parts[::-1].index("apk")
    if i + 2 >= len(parts):
        return None
    return parts[i + 1], parts[i + 2]


def build_config_url(flavor: str, build_type: str) -> tuple[str, Path | None]:
    hits = list((ROOT / "android/app/build/generated/source/buildConfig" / flavor / build_type)
                .rglob("BuildConfig.java")) if (ROOT / "android/app/build/generated/source/buildConfig" / flavor / build_type).is_dir() else []
    if not hits:
        return "", None
    text = hits[0].read_text(encoding="utf-8", errors="replace")
    m = re.search(r'API_BASE_URL\s*=\s*"([^"]*)"', text)
    return (m.group(1) if m else ""), hits[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apk", type=Path,
                    default=ROOT / "android/app/build/outputs/apk/phone/debug/app-phone-debug.apk")
    args = ap.parse_args()
    apk: Path = args.apk
    if not apk.is_file():
        print(f"❌ 找不到包：{apk}\n   先打：gradle -p android assemblePhoneDebug")
        return 1

    r = subprocess.run([str(aapt2()), "dump", "badging", str(apk)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print("❌ aapt2 dump badging 失败：\n" + (r.stderr or ""))
        return 1
    m = re.search(r"package: name='([^']+)' versionCode='(\d+)' versionName='([^']*)'", r.stdout)
    abis = re.search(r"native-code: (.+)", r.stdout)
    name, code, ver = (m.group(1), m.group(2), m.group(3)) if m else ("?", "?", "?")
    print(f"包：{apk}")
    print(f"  应用：{name}   版本：{ver}（versionCode {code}）")
    print(f"  架构：{abis.group(1) if abis else '（没有 native 库）'}")
    print(f"  大小：{apk.stat().st_size / 1024 / 1024:.1f} MB")

    props_url = prop("api_base_url")
    # 变体**从包路径推**（`--apk` 可以指 debug 也可以指 release），推不出来才退回 phone/debug
    variant = variant_of(apk)
    if variant is None:
        flavor, build_type = "phone", "debug"
        print(f"  ⚠️ 这个包的路径不像标准产物，按 {flavor}/{build_type} 读 BuildConfig")
    else:
        flavor, build_type = variant
    bc_url, bc_path = build_config_url(flavor, build_type)
    print(f"  local.properties 里：{props_url or '（没写）'}")
    print(f"  编译时 BuildConfig（{flavor}/{build_type}）：{bc_url or '（找不到生成文件）'}")

    bad = 0
    if any(props_url.startswith(h) for h in EMULATOR_HOSTS):
        # ⚠️ 这只是**提醒**，不算不过：打完真机包把 local.properties 改回模拟器地址是**正常操作**
        #    （否则模拟器联调会去连生产）。真正要拦的是"包本身连的是模拟器地址"。
        print(f"  ⚠️ 提醒：local.properties 现在还是模拟器地址（{props_url}）——"
              f"下次打真机包记得先改成 {PROD_HINT}，打完再改回来。")
    if any(bc_url.startswith(h) for h in EMULATOR_HOSTS):
        print(f"❌ 这个包编译时用的是模拟器地址（{bc_url}）——装到真机上会连不上。重打。")
        bad += 1
    if bc_path and apk.stat().st_mtime < bc_path.stat().st_mtime:
        print(f"⚠️ 包比 BuildConfig 旧（{apk.name}），核对的是不是同一个构建？")
        bad += 1
    if not abis or "arm64-v8a" not in abis.group(1):
        print("❌ 不是真机包（没有 arm64-v8a）——是不是打成了 emu flavor？")
        bad += 1
    if bc_url and not bc_url.startswith("http"):
        print(f"❌ BuildConfig 里的地址不像 URL：{bc_url}")
        bad += 1
    # 正向确认：dex 里真的编进了那个生产地址（说明这次构建生效了，不是缓存）
    if bc_url:
        with zipfile.ZipFile(apk) as z:
            blob = b"".join(z.read(n) for n in z.namelist() if n.endswith(".dex"))
        if bc_url.encode() not in blob:
            print(f"❌ dex 里找不到 {bc_url}——构建缓存没更新？（gradle clean 后再打）")
            bad += 1
    print("  ℹ️ 包里另有 http://10.0.2.2:8000 是**正常的**：那是 ApiEndpoint 的模拟器兜底常量，"
          "真机上 isEmulator()=false 永远走不到，别去删它。")

    if bad:
        print(f"\n❌ {bad} 项不过，别发。")
        return 1
    print("\n✅ 可以发：编译用的是服务端地址、架构含 arm64-v8a、dex 里确实编进了该地址。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
