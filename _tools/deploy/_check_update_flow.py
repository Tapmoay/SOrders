#!/usr/bin/env python3
"""应用内更新链路的红线检查（对应 2026-09-15 用户报的「下载慢 + 下载完没更新」）。

为什么需要它：应用内更新是**跨 5 个地方**的一条链——
  file_paths.xml（FileProvider 允许的根目录）
  ProfileViewModel.kt（下载到哪、怎么调起安装器）
  build.gradle.kts（versionCode 方案 / ABI 分流）
  backend/app/main.py（.apk 的 Content-Type）
  _tools/deploy/publish_apk.py（推包时的版本号闸门）
任何一处改错，都是"下载完成了但什么都没发生"，而且**没有任何报错**——
用户只会说"下载完没更新"，开发者从日志里也看不出所以然。
所以把这些不变量固化成检查，改坏了立刻红。

跑：python _tools/deploy/_check_update_flow.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Windows 控制台默认是 GBK，脚本里只要有非 GBK 字符（比如 ↳），
# **在检查失败、准备打印原因的那一刻**就会 UnicodeEncodeError 崩掉——
# 也就是"检查能发现问题，但你看不到是哪个问题"。所以强制 stdout 用 UTF-8。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android" / "app" / "src" / "main"
VM = AND / "java" / "com" / "tapmoay" / "sorders" / "ui" / "profile" / "ProfileViewModel.kt"
SCREEN = AND / "java" / "com" / "tapmoay" / "sorders" / "ui" / "profile" / "ProfileScreen.kt"
PROGRESS = AND / "java" / "com" / "tapmoay" / "sorders" / "ui" / "profile" / "UpdateProgress.kt"
PATHS_XML = AND / "res" / "xml" / "file_paths.xml"
GRADLE = ROOT / "android" / "app" / "build.gradle.kts"
MAIN_PY = ROOT / "backend" / "app" / "main.py"
PUBLISH = ROOT / "_tools" / "deploy" / "publish_apk.py"
NGINX_FIX = ROOT / "_tools" / "deploy" / "_fix_nginx_static.py"

results: list[tuple[bool, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((ok, name, detail))


def text(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.is_file() else ""


def brace_block(src: str, start: int) -> str:
    """从 start 处的 '{' 开始，返回配平到对应 '}' 的子串（够用即可，不处理字符串里的花括号）。"""
    depth = 0
    for i in range(start, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
    return src[start:]


def fn_block(src: str, signature: str) -> str:
    i = src.find(signature)
    if i < 0:
        return ""
    j = src.find("{", i)
    return brace_block(src, j) if j >= 0 else ""


# ── 1. FileProvider 根目录 必须覆盖 APK 落盘目录（当初就是这里错的）──────────
vm = text(VM)
paths = text(PATHS_XML)
m = re.search(r'val UPDATE_DIR\s*=\s*"([^"]+)"', vm)
update_dir = m.group(1) if m else ""
check("ProfileViewModel 里有 UPDATE_DIR 常量", bool(update_dir), f"UPDATE_DIR={update_dir!r}")

roots = re.findall(r'<cache-path[^>]*path="([^"]*)"', paths)
check("file_paths.xml 声明了 cache-path 根", bool(roots), f"roots={roots}")

covered = any(
    r.rstrip("/") == update_dir.rstrip("/") or update_dir.startswith(r.rstrip("/") + "/")
    for r in roots
)
check(
    f"APK 落盘目录 '{update_dir}' 被 file_paths.xml 的某个 cache-path 覆盖",
    covered,
    f"roots={roots}；不覆盖的话 getUriForFile 抛 IllegalArgumentException，"
    f"现象=进度 100% 后毫无反应",
)

check(
    "APK 写在 cacheDir/<UPDATE_DIR> 下（不是 cacheDir 根下）",
    "File(ctx.cacheDir, UPDATE_DIR)" in vm,
)

# ── 2. 下载循环里不能每个分片切一次主线程 ────────────────────────────────
loop = fn_block(vm, "private suspend fun download(")
check("能找到 download() 实现", bool(loop))
if loop:
    read_loop = ""
    k = loop.find("while (true)")
    if k >= 0:
        read_loop = brace_block(loop, loop.find("{", k))
    check("找到字节读取循环", bool(read_loop))
    check(
        "读取循环内不再 withContext(Dispatchers.Main)（每 64KB 一次主线程往返）",
        "Dispatchers.Main" not in read_loop,
        "旧写法每个 64KB 分片都要往返主线程一次（40MB ≈ 600 次），拖慢下载且没法单测",
    )
    check("下载带断点续传（发 Range 头）", 'header("Range"' in loop)
    check("下载后校验 zip 魔数（拦掉服务器错误页）", "looksLikeZip" in loop)
    check("大小不符时报「下载不完整」而不是当成功", "下载不完整" in loop)

# ── 3. 安装器调起 + 未知来源权限 ─────────────────────────────────────────
check("调起安装器前包了 try/catch 并给人话", "安装包已经下好了，但系统不认它的存放路径" in vm)
check("下载前先检查能否安装应用（别白下 40MB）", "canInstallPackages(ctx)" in vm)
check("能跳到「安装未知应用」设置页", "ACTION_MANAGE_UNKNOWN_APP_SOURCES" in vm)
check("UI 有这一步的引导弹窗", "还差一步：允许安装应用" in text(SCREEN))
check("UI 下载中显示速度/剩余（不再是只有百分比）", "downloadDetail" in text(SCREEN))

# ── 4. 文案逻辑保持纯函数（可单测）────────────────────────────────────────
prog = text(PROGRESS)
check("UpdateProgress.kt 存在", bool(prog))
check("UpdateProgress 不 import android.*（否则进不了 JVM 单测）", "import android" not in prog)
test_file = AND.parent / "test" / "java" / "com" / "tapmoay" / "sorders" / "ui" / "profile" / "UpdateProgressTest.kt"
check("UpdateProgress 有单测", test_file.is_file(), str(test_file))

# ── 5. versionCode 方案（混量纲 = 后打的包装不上）─────────────────────────
g = text(GRADLE)
check(
    "build.gradle.kts 不再用秒级时间戳当 versionCode 缺省值",
    "System.currentTimeMillis() / 1000" not in g,
    "时间戳 1789426316 与日期式 2026091501 不同量纲，混用会让后打的包 versionCode 更小 → "
    "安卓拒装，现象同样是「下载完没更新」",
)
check("versionCode 缺省值是日期式 yyyyMMdd*100+n", re.search(r'yyyyMMdd".*?toInt\(\)\s*\*\s*100', g) is not None)
check("有 phone / emu 两个 ABI flavor（整包瘦身）", "create(\"phone\")" in g and "create(\"emu\")" in g)
check("phone flavor 只带 arm64-v8a / armeabi-v7a", '"arm64-v8a", "armeabi-v7a"' in g)
check(
    "没有用 splits.abi（它的 versionCode 会乘 10 撑爆 int）",
    "splits {" not in g,
    "2026091501 * 10 = 20260915010 > Int.MAX(2147483647)",
)

# ── 5b. 版本号正规化（2026-09-21 用户要求「版本号做一个正规化的处理」）────────
# 这一节钉的是"版本号只有一个说法"：产品版本（versionName）来自仓库根 VERSION、
# 构建号（versionCode）保持日期式且由发布脚本算号。四条判据都要**能红**：
#   ① 把 versionName 改回写死的 `1.0.0.<日期>` → 第一条红；
#   ② 删掉 `--next-code`（回到"让发布者自己心算号"）→ 第二条红；
#   ③ 上传文件名去掉构建号 → 第三条红（产品版本语义化之后同日第二个包会覆盖第一个）；
#   ④ 把 -PapiBaseUrl 提示改回 http → 第四条红。
_pub_early = text(PUBLISH)
check(
    "versionName 的缺省值来自仓库根 VERSION（不是写死的 1.0.0.<日期>）",
    'rootProject.file("../VERSION")' in g and '"1.0.0." +' not in g,
    "同一个产品出现「0.2.0」和「1.0.0.20260921」两个版本号，用户报版本时两边对不上；"
    "backend/app/config.py 读的就是这个 VERSION 文件",
)
check(
    "发布脚本能算出「这次该用哪个构建号」（--next-code）",
    "--next-code" in _pub_early and "def next_code(" in _pub_early,
    "日期式缺省值只给到「今天第 1 个包」，而一天会打两三个；让人心算就会撞闸，"
    "而闸门原来只丢一句「请提高版本号」",
)
check(
    "上传文件名带构建号（同日第二个包不会覆盖第一个）",
    "sorders-{name}-{code}.apk" in _pub_early,
    "versionName 语义化之后（0.2.0 这种）文件名会重复 → 覆盖线上包，--keep 也留不住历史",
)
check(
    "打包提示里的 -PapiBaseUrl 是 https（不是 http）",
    "PROD_API_BASE" in _pub_early and '-PapiBaseUrl=http://' not in _pub_early,
    "发布包禁明文：network_security_config 是 cleartextTrafficPermitted=false，"
    "SocketManager 在非 DEBUG 下拒绝非 https 长连接 —— 照 http 打包会「装得上但用不了」",
)

# ── 6. 服务端 .apk 的 Content-Type ──────────────────────────────────────
mp = text(MAIN_PY)
check(
    "后端静态路由把 .apk 标成 application/vnd.android.package-archive",
    "application/vnd.android.package-archive" in mp,
    "不写的话 Starlette 的 FileResponse 会退回 text/plain，手机浏览器去『渲染』几十 MB 二进制",
)
check("后端给了 Content-Disposition: attachment", "Content-Disposition" in mp)
check("有 nginx 直出 /static/uploads/ 的脚本（别让慢客户端占死 uvicorn worker）", NGINX_FIX.is_file())

# ── 7. 推包脚本的版本号闸门 ─────────────────────────────────────────────
pub = text(PUBLISH)
check("publish_apk.py 存在", bool(pub))
check("推包前比较线上 versionCode，不更大就中止", "不大于线上" in pub)
check("version.json 里写入 versionCode", '"versionCode": code' in pub)
check("推完回读 version.json 验证生效", "回读" in pub)
check("推完探测 APK 响应头（206 + 正确 Content-Type）", "Content-Range" in pub)
check(
    "推包前检查包里的后端地址不是开发地址",
    "DEV_URL_PATTERNS" in pub and "baked_api_base_url" in pub,
    "组进 10.0.2.2 的包发到真机 = App 连不上后端；现象和「更新失败」完全不像，会绕远路排查",
)
check(
    "后端地址取自 AGP 生成的 BuildConfig.java（而不是 local.properties）",
    "generated" in pub and "BuildConfig.java" in pub,
    "local.properties 可能在构建之后被改过，只有 BuildConfig 是真正编进包里的值",
)

# ── 输出 ────────────────────────────────────────────────────────────────
bad = [r for r in results if not r[0]]
for ok, name, detail in results:
    mark = "OK  " if ok else "FAIL"
    print(f"[{mark}] {name}")
    if not ok and detail:
        print(f"        -> {detail}")
print()
print(f"共 {len(results)} 项检查：通过 {len(results) - len(bad)}，失败 {len(bad)}")
sys.exit(1 if bad else 0)
