"""一把装三台：**构建一次 → 给三台模拟器重装 APK → 各自登录 → 汇报**（共享工具，谁都能用）。

用户 2026-09-21 原话：
> 「3 个模拟器一起重装 apk 并且登录的那个脚本……如果没有那个脚本的话你写一个，
>   然后声明一下通知其他的工作人员，也有一个工具大家以后都用这个工具更新 apk。
>   但是有个前提：**假如某个人他正在干活的话，则就不需要调用这个脚本了，就各装各就行了**。」

## 为什么要有它
三个端各装一次、各登一次，是每轮改完 UI 都要做的动作。手工做有四个反复踩的坑：
① **忘装某一台**，于是"我这边好了"和"他那边没变"同时成立，查半天；
② 三台装的**不是同一个包**（有人 `assemblePhoneDebug`、有人 `assembleEmuDebug`），
   表现是"同一个功能两台表现不一样"；
③ 密码/账号记混（5554=派单员、5556=货主、5558=司机，**不是**按端口顺序排的角色）；
④ 登录页**键盘弹出会改 y**，按写死的坐标点会把密码串进手机号栏（`_emu_ui.py` 的 KDoc 记过这次事故）。

## 「有人在干活就别用」怎么判（fail-closed，每一条都会说清"看到了什么 + 怎么办"）
1. **别人正在构建**：进程表里有 Gradle 构建在跑 → 两个构建撞在一起会互相等锁、还会抢同一个
   `build/` 目录（本仓库实测过"构建输出被占用"）。→ 拒绝。
2. **别人正在改 App**：别的会话最近几分钟还在写日志（看会话日志 mtime，**不是**看声明页
   —— 声明页「进行中」积压历史条目，拿它做门禁会天天误报）。
   ⛔ 这一条就是用户说的那个前提：**他在干活，就各装各的** —— 你装你的包，他装他的，
   别让"一把装三台"把他正在调的那台刷成你的版本（他会以为自己的改动没生效）。
   ⚠️ **`--only <端口>` 时这一条降级为提醒、不再拦**（2026-09-21 修）：`--only` 本身就是
   "各装各的"——都只装自己那一台了，还拦着不让装就自相矛盾（上一版就是这样：
   预检打印"照规矩各装各的（--only）"，然后照样拒绝）。**构建在跑**那一条仍然拦，
   因为两个 Gradle 撞一起是物理冲突，跟装哪台无关。
3. 设备不在线：只装在线的那几台，并**明确说哪台没装**（不静默跳过）。

明知有人在干活也要装：`--force`（会把"我知道有人在做"写进输出，出事有据可查）。

## 用法
```
python _tools/qa/_install_all.py                 # 预检 → 构建 → 装三台 → 登录 → 汇报
python _tools/qa/_install_all.py --precheck      # 只跑预检（不构建不装），看能不能用
python _tools/qa/_install_all.py --only 5556     # 只装一台（其余不动）＝「各装各的」，
                                                 #   别人在干活时就用这个（这时预检只提醒不拦）
python _tools/qa/_install_all.py --no-build      # 用现有 APK（省一次构建）
python _tools/qa/_install_all.py --fresh         # 先 pm clear（强制走一遍真登录）
python _tools/qa/_install_all.py --force         # 有人在干活也照装
```
退出码：0 = 全部成功；1 = 有台没装成/没登成（**明细在最后那张表**）；2 = 预检拒绝。
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _emu_ui as ui  # noqa: E402  —— 按文字定位那一套只有一份，别再写一遍

ROOT = Path(__file__).resolve().parents[2]
APK = ROOT / "android" / "app" / "build" / "outputs" / "apk" / "emu" / "debug" / "app-emu-debug.apk"
GRADLE = ROOT / "_agent" / "gradle" / "gradle-8.9" / "bin" / "gradle.bat"
JAVA_HOME = r"D:\APPS\AndroidStudio\jbr"
CLAIM = ROOT / "docs" / "AI_WORK_CLAIM.md"
PKG = "com.tapmoay.sorders"

# 端口 → 角色 / 账号 / AVD / 该角色界面上能看到的标志文字。
# ⚠️ **角色不是按端口排的**：5554 是派单员、5556 是货主、5558 是司机。
# （2026-09-21 实测核对过：`adb -s <port> emu avd name` 分别是 SOrdersD / SOrdersAI / SOrdersDriver）
# 标志文字给**多个**：登录后 App 不一定停在工作台（派单员实测落在「派单作业」那一页），
# 只认一个的话会误报"没抓到角色"。
DEVICES: list[tuple[str, str, str, str, tuple[str, ...]]] = [
    ("5554", "派单员", "13800000001", "SOrdersD", ("派单端 · 全量管理", "派单作业", "待派单池")),
    ("5556", "货主", "13800000002", "SOrdersAI", ("货主端 · 订单与账本", "我的订单")),
    ("5558", "司机", "13800000003", "SOrdersDriver", ("已完成", "进行中")),
]
# 判「登错了角色」只用这几个**强标志**（弱标志如「进行中」在别处也会出现，会误伤）
STRONG_MARK = ("派单端 · 全量管理", "货主端 · 订单与账本")
PASSWORD = "123321"

# 系统权限弹窗里我们倾向点哪个（按优先级）
PERM_PREFER = ("Allow all", "While using the app", "Allow", "允许")


def sh(args: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", **kw)


def adb(serial: str, *args: str) -> subprocess.CompletedProcess:
    return sh([ui.ADB, "-s", f"emulator-{serial}", *args])


def devices_online() -> set[str]:
    out = sh([ui.ADB, "devices"]).stdout or ""
    return {m.group(1) for m in re.finditer(r"emulator-(\d{4})\s+device", out)}


def gradle_busy() -> str | None:
    """有没有别人正在跑 Gradle 构建。返回那一行（给用户看证据）。

    ⚠️ 第一版是**扫进程表**里含 `gradle-8.9` 的命令行 —— **天天误报**：
    Gradle 守护进程是常驻的（空闲时也在），它的命令行里就带那个字样，
    于是"有人在构建"永远成立、这个工具就永远不能用（实测每次预检都拦）。
    改用 Gradle 自己的 `--status`：它明确写 `IDLE` / `BUSY`。
    """
    if not GRADLE.exists():
        return None
    r = sh([str(GRADLE), "-p", "android", "--status"],
           env=dict(os.environ, JAVA_HOME=JAVA_HOME))
    for ln in ((r.stdout or "") + (r.stderr or "")).splitlines():
        if "BUSY" in ln:
            return ln.strip()
    return None


def other_active_sessions(minutes: float, me: str | None) -> list[tuple[str, float]]:
    """**别的会话最近有没有动静** —— 直接看 DSH 会话日志的 mtime（它就是"谁在干活"的证据）。

    为什么不用声明页（`AI_WORK_CLAIM.md`）当判据：那里「进行中」一节积压了**大量历史条目**
    （实测一口气命中 10 条，大半是早就做完的轮次），拿它当门禁等于天天拦路。
    会话日志 mtime 是**行为**而不是**声明**：还在写 = 真的在干活。
    （本机实测：正在跑的那个会话，它的 `session.v2.jsonl.zstd` mtime 就是"现在"。）

    ⚠️ 已知盲区：**人手工改代码**时它看不出来（那没有会话日志）。
    """
    root = Path(os.environ.get("DSH_HOME", str(Path.home() / ".dsh"))) / "sessions"
    if not root.exists():
        return []
    now = time.time()
    mine = {(me or ""), (me or "").replace("session-", "")}
    out: list[tuple[str, float]] = []
    for log in root.glob("*/*/session.v2.jsonl.zstd"):
        if log.parent.name in mine:
            continue
        try:
            age = (now - log.stat().st_mtime) / 60.0
        except OSError:
            continue
        if age <= minutes:
            out.append((log.parent.name, age))
    return sorted(out, key=lambda x: x[1])


def unrelated_claims(session: str | None) -> list[tuple[str, str]]:
    """声明页里别人点名了 `android/` 的条目 —— **只当参考，不当判据**。

    它的价值是回答"如果真有人在干，是谁、在改什么"；拿它做门禁会误伤（见上一条的注释）。
    只认顶层条目（`### … 会话：…`），跳过「第三轮：…」那种子标题。
    """
    if not CLAIM.exists():
        return []
    text = CLAIM.read_text(encoding="utf-8", errors="replace")
    body = text.split("## 进行中", 1)[-1].split("## 已完成", 1)[0]
    blocks = re.split(r"^### ", body, flags=re.M)[1:]
    out: list[tuple[str, str]] = []
    for b in re.split(r"^### ", body, flags=re.M)[1:]:
        head = b.splitlines()[0]
        if "会话：" not in head:          # 只要顶层条目，跳过「第三轮：…」这种子标题
            continue
        sid = re.search(r"session-[0-9a-f-]+", b)
        if session and sid and sid.group(0) == session:
            continue                      # 我自己那条，跳过
        if "android/" not in b:
            continue
        who = head[:80]
        files = sorted({m.group(0) for m in re.finditer(r"android/[\w./\-]+\.kt", b)})[:3]
        out.append((who, "、".join(Path(f).name for f in files) or "（条目里提到 android/）"))
    return out


def precheck(session: str | None, force: bool, active_min: float, only: str | None = None) -> int:
    print("== 预检：现在适不适合「一把装三台」 ==")
    bad = False
    busy = gradle_busy()
    if busy:
        bad = True
        print("  ❌ 有 Gradle 构建正在跑（会互相抢 build/ 与锁）：")
        print(f"     {busy[:160]}")
        print("     → 等它跑完再装（**这一条 --only 也不能绕**：两个构建撞一起是物理冲突）。")
    else:
        print("  ✅ 没有别的构建在跑")

    claims = unrelated_claims(session)
    others = other_active_sessions(active_min, session)
    if others:
        print(f"  {'⚠️' if only else '❌'} 有 {len(others)} 个**别的会话**这几分钟还在干活"
              f"（{active_min:g} 分钟内写过日志）：")
        for sid, age in others[:5]:
            print(f"     · {sid}（{age:.1f} 分钟前还在写）")
        if only:
            # `--only` 就是用户说的"各装各的"：只装自己那一台，所以这一条**只提醒、不拦**
            print(f"     → 你给的是 --only {only}（＝各装各的）：确认 {only} 不是他正在调的那台，就继续。")
            print("        别顺手去掉 --only 装三台 —— 那才会把他那台刷成你的版本。")
        else:
            bad = True
            print("     → 用户定的前提：「他在干活就各装各的」——"
                  "别把他正在调的那台刷成你的包（他会以为自己的改动没生效）。")
            print("        照规矩的做法：加 --only <你自己的端口> 只装一台。")
    else:
        print(f"  ✅ 没有别的会话在干活（{active_min:g} 分钟内，本会话 = {session or '未识别'}）")
    if claims:
        # 只当参考：声明页「进行中」积压了历史条目，拿它做门禁会天天误报
        print(f"  ℹ️ 参考：声明页「进行中」里有 {len(claims)} 条别的会话点名了 android/（可能含历史条目）：")
        for who, files in claims:
            print(f"     · {who}  →  {files}")

    online = devices_online()
    miss = [p for p, *_ in DEVICES if p not in online]
    print(f"  {'✅' if not miss else '⚠️'} 在线设备：{sorted(online)}"
          + (f"（缺 {'、'.join(miss)}，那几台会跳过）" if miss else ""))

    if bad and not force:
        print("\n结论：**现在不适合**。有人在干活 —— 照用户定的规矩：各装各的（--only <你的端口>）。")
        print("      明知故犯要装：加 --force。")
        return 2
    if bad:
        print("\n⚠️ 预检有意见，但你给了 --force，继续（理由请自己记住）。")
    print("\n结论：可以装。")
    return 0


def build() -> bool:
    if not GRADLE.exists():
        print(f"❌ 找不到 Gradle：{GRADLE}")
        return False
    print("== 构建一次（三台共用同一个包）==")
    env = dict(os.environ, JAVA_HOME=JAVA_HOME)
    r = sh([str(GRADLE), "-p", "android", "assembleEmuDebug", "--console=plain"],
           cwd=str(ROOT), env=env)
    tail = [ln for ln in ((r.stdout or "") + (r.stderr or "")).splitlines()
            if "BUILD" in ln or ln.startswith("e: ")]
    for ln in tail[-6:]:
        print("   " + ln)
    if r.returncode != 0 or not APK.exists():
        print("❌ 构建失败（或没产出 APK）")
        return False
    print(f"   ✅ {APK.relative_to(ROOT).as_posix()}"
          f"（{APK.stat().st_size / 1048576:.1f}MB，{time.strftime('%H:%M:%S', time.localtime(APK.stat().st_mtime))}）")
    return True


def dismiss_dialogs(serial: str, rounds: int = 6) -> None:
    """关掉系统权限弹窗（清过数据的机器一登录就连着弹定位/通知/相册）。

    ⚠️ 三个「Allow」是按**精确文本**点的：`_find` 用的是子串，
    点 "Allow" 会先命中 "Allow limited access"（实测点错过）。
    """
    for _ in range(rounds):
        rows = ui._nodes(ui._dump_xml(f"emulator-{serial}"))
        texts = [t for t, *_ in rows if t]
        hit = None
        for want in PERM_PREFER:
            if any(t.strip() == want for t in texts):
                hit = want
                break
        if hit is None:
            return
        exact = [r for r in rows if r[0].strip() == hit]
        x, y = exact[0][2]
        adb(serial, "shell", "input", "tap", str(x), str(y))
        time.sleep(1.2)


def login_if_needed(serial: str, phone: str) -> str:
    """在登录页就登录。返回一句人话（成功/已在登录态/失败）。"""
    rows = ui._nodes(ui._dump_xml(f"emulator-{serial}"))
    texts = [t for t, *_ in rows if t]
    if not any("手机号" in t for t in texts):
        return "已在登录态（没看到登录页）"
    def tap(needle: str) -> bool:
        hit = ui._find(ui._dump_xml(f"emulator-{serial}"), needle)
        if not hit:
            return False
        adb(serial, "shell", "input", "tap", str(hit[2][0]), str(hit[2][1]))
        time.sleep(0.8)
        return True

    if not tap("手机号"):
        return "❌ 找不到手机号输入框"
    adb(serial, "shell", "input", "text", phone)
    time.sleep(0.8)
    if not tap("密码"):
        return "❌ 找不到密码输入框"
    adb(serial, "shell", "input", "text", PASSWORD)
    time.sleep(0.8)
    # 关键一步：**先关掉键盘再点登录** —— 键盘会盖住按钮（且布局会变，坐标不能写死）
    adb(serial, "shell", "input", "keyevent", "KEYCODE_BACK")
    time.sleep(0.8)
    if not tap("登"):
        return "❌ 找不到登录按钮"
    time.sleep(6)
    dismiss_dialogs(serial)
    time.sleep(2)
    after = [t for t, *_ in ui._nodes(ui._dump_xml(f"emulator-{serial}")) if t]
    if any("手机号" in t for t in after):
        return "❌ 登录失败（还停在登录页）"
    return "✅ 登录成功"


def verify_role(serial: str, want: tuple[str, ...]) -> str:
    """核对这台现在登的是**它该有的那个角色**（混角色是"我这边明明好了"的头号来源）。"""
    texts = [t for t, *_ in ui._nodes(ui._dump_xml(f"emulator-{serial}")) if t]
    joined = " | ".join(texts)
    hit = next((m for m in want if m in joined), None)
    if hit:
        return f"✅ 角色对（看到「{hit}」）"
    wrong = next((m for m in STRONG_MARK if m in joined and m not in want), None)
    if wrong:
        return f"❌ 角色不对：看到的是「{wrong}」—— 这台该是另一个角色"
    if any("手机号" in t for t in texts):
        return "❌ 还停在登录页"
    return "ℹ️ 已登录（没抓到角色标志文字，请自己扫一眼）"


def install_one(serial: str, role: str, phone: str, avd: str,
                want: tuple[str, ...], fresh: bool) -> str:
    print(f"\n-- emulator-{serial}｜{role}｜{phone}｜AVD {avd} --")
    if fresh:
        adb(serial, "shell", "pm", "clear", PKG)
        print("   已 pm clear（强制走一遍真登录）")
    r = adb(serial, "install", "-r", str(APK))
    out = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
    if r.returncode != 0 or not any("Success" in ln for ln in out):
        print("   ❌ 安装失败：" + (out[-1] if out else "（无输出）"))
        return "❌ 安装失败"
    print("   ✅ 装好了")
    adb(serial, "shell", "am", "force-stop", PKG)
    adb(serial, "shell", "am", "start", "-n", f"{PKG}/.MainActivity")
    time.sleep(7)
    dismiss_dialogs(serial)
    res = login_if_needed(serial, phone)
    print(f"   {res}")
    check = verify_role(serial, want)
    print(f"   {check}")
    shown = [t for t, *_ in ui._nodes(ui._dump_xml(f"emulator-{serial}")) if t][:6]
    print("   屏上：" + " | ".join(shown)[:110])
    return f"{res.split('（')[0]} · {check.split('（')[0]}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None, help="只装这个端口（5554/5556/5558）")
    ap.add_argument("--no-build", action="store_true", help="不构建，直接用现有 APK")
    ap.add_argument("--fresh", action="store_true", help="先 pm clear（要真登录一遍）")
    ap.add_argument("--force", action="store_true", help="预检有意见也照装")
    ap.add_argument("--precheck", action="store_true", help="只跑预检")
    ap.add_argument("--session", default=os.environ.get("DSH_SESSION_ID"),
                    help="本会话 id（默认取 $DSH_SESSION_ID）：用来把"
                         "『我自己』从『别人在干活』里排除掉")
    ap.add_argument("--active-min", type=float, default=6.0,
                    help="多久之内算『还在干活』（分钟，默认 6）")
    a = ap.parse_args()

    rc = precheck(a.session, a.force, a.active_min, a.only)
    if a.precheck or rc == 2:
        return rc

    online = devices_online()
    todo = [d for d in DEVICES if (a.only is None or d[0] == a.only) and d[0] in online]
    skipped = [d[0] for d in DEVICES if (a.only is None or d[0] == a.only) and d[0] not in online]
    if not todo:
        print(f"❌ 没有可装的设备（在线：{sorted(online)}，--only={a.only}）")
        return 1
    if skipped:
        print(f"⚠️ 跳过不在线的：{'、'.join(skipped)}")

    if not a.no_build and not build():
        return 1
    if not APK.exists():
        print(f"❌ 没有 APK：{APK.relative_to(ROOT).as_posix()}（先去掉 --no-build 构建一次）")
        return 1

    results: list[tuple[str, str, str]] = []
    for serial, role, phone, avd, want in todo:
        results.append((serial, role, install_one(serial, role, phone, avd, want, a.fresh)))

    print("\n" + "=" * 62)
    print("端口    角色     账号          结果")
    for serial, role, res in results:
        print(f"{serial:<7} {role:<8} "
              f"{dict((d[0], d[2]) for d in DEVICES)[serial]:<13} {res}")
    bad = [r for r in results if not r[2].startswith(("✅", "已在"))]
    print(f"\n{len(results) - len(bad)}/{len(results)} 台就绪"
          + (f"；{len(bad)} 台有问题（见上表）" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
