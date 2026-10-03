"""反向验证 CHG-0030（后台接收对所有角色都开）那批修复**真的在检查**。

2026-10-04 用户点名：消息提醒按角色统一 —— **所有角色后台都能接收**，语音只有派单员与司机。
修法是「缺省改成恒真 + 常驻通知 / 设置页那一档 / 状态那一行都按角色说 + 渠道名不再写死成派单」，
这份脚本逐条把修复撤回，证明对应的检查（判据脚本 / Android 单测）会红。

| 注入 | 应该红的检查 |
|---|---|
| 缺省改回按语音分（货主 / 批发商又变成仅前台） | Android 单测「所有角色都默认后台常驻」 |
| 缺省恒假 / AlertPrefs 不再走那条缺省 | 判据 |
| 常驻通知其余角色那支改成司机那句 | Android 单测「常驻通知按角色说要收的是什么」 |
| 常驻通知标题写死 / 常驻服务不问当前角色 | 判据 |
| 渠道名与描述改回写死「派单」 | 判据 |
| 设置页那一档的标题 / 副标题写死 | 判据 |
| 设置页其余角色那支改成司机版 | Android 单测「设置页那一档也按角色说要收的是什么」 |
| 状态那一行关掉后台时不再提「仅前台接收」 | Android 单测「司机的摘要要说清语音和后台两件事」 |
| 货主那一支的摘要恒写「后台接收中」 | 判据 |
| 派单员那句被改成司机那句 | 判据（司机那句只许出现一次） |
| 回归用例被改名 | 判据 |

⚠️ 快照/还原按**字节**做（仓库里有 CRLF 文件），跑完逐字节核对。
⚠️ 最后几条注入是**真跑一遍 Android 单测**（gradle），它会覆盖 `android/app/build/test-results/`：
   跑完请重跑一次 gradle，否则 `_tools/qa/_android_test_count.py` 会读到 failures>0。
⚠️ 跑的时候拿着注入锁（`_airepo.lock_reverse_verify`）：并发的检查会拒绝出结论。

用法：python _tools/qa/_reverse_verify_alert_background_all_roles.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_tools/ai"))

from _airepo import lock_reverse_verify, unlock_reverse_verify  # noqa: E402

JUDGE = ROOT / "_tools/qa/_check_alert_background_all_roles.py"
GRADLE = ROOT / "_agent/gradle/gradle-8.9/bin/gradle.bat"

ALERT = "android/app/src/main/java/com/tapmoay/sorders/core/NewOrderAlert.kt"
PREFS = "android/app/src/main/java/com/tapmoay/sorders/core/AlertPrefs.kt"
SVC = "android/app/src/main/java/com/tapmoay/sorders/core/AlertService.kt"
CENTER = "android/app/src/main/java/com/tapmoay/sorders/core/NotifyCenter.kt"
SETTINGS = "android/app/src/main/java/com/tapmoay/sorders/ui/profile/AlertSettingsScreen.kt"
KTEST = "android/app/src/test/java/com/tapmoay/sorders/core/NewOrderAlertTest.kt"

DEFAULT = "fun defaultBackground(role: Role?): Boolean = true"
#: 常驻通知里司机那句（逐字，判据数它出现的次数）
DRIVER_NOTICE = 'AlertKind.NEW_ORDER -> "SOrders 正在后台接收派单" to "有新派单会立刻提醒你"'
#: 设置页那一档里司机那行（逐字）
DRIVER_ROW = 'AlertKind.NEW_ORDER -> "关掉 App 也收单" to "关闭后只有打开 App 时才收得到新派单"'
CLASS = "`所有角色都默认后台常驻`"

#: (说明, 相对路径, 注入, 期望变红的 node)；`CHECK:` = 跑判据脚本找那条 [FAIL]，`GRADLE:` = 真跑 Android 单测
CASES: list[tuple[str, str, object, str]] = [
    (
        "缺省改回按语音分（货主 / 批发商又变成仅前台接收）",
        ALERT,
        lambda s: s.replace(DEFAULT, "fun defaultBackground(role: Role?): Boolean = hasVoice(role)", 1),
        "GRADLE:testEmuDebugUnitTest",
    ),
    (
        "缺省恒假（所有人都不再后台接收）",
        ALERT,
        lambda s: s.replace(DEFAULT, "fun defaultBackground(role: Role?): Boolean = false", 1),
        "CHECK:后台常驻的缺省对所有角色都开",
    ),
    (
        "AlertPrefs 不再走那条缺省（没设置过时一律关）",
        PREFS,
        lambda s: s.replace("else NewOrderAlert.defaultBackground(role)", "else false", 1),
        "CHECK:AlertPrefs 没设置过时走那条缺省",
    ),
    (
        "常驻通知里其余角色那支被改成司机那句",
        ALERT,
        lambda s: s.replace(
            'AlertKind.REVOKED, null -> "SOrders 正在后台接收消息" to "有新消息会立刻提醒你"',
            'AlertKind.REVOKED, null -> "SOrders 正在后台接收派单" to "有新派单会立刻提醒你"',
            1,
        ),
        "GRADLE:testEmuDebugUnitTest",
    ),
    (
        "常驻通知的标题写死成司机那句（不再由调用方给）",
        CENTER,
        lambda s: s.replace(
            ".setContentTitle(title)\n            .setContentText(text)",
            '.setContentTitle("SOrders 正在后台接收派单")\n            .setContentText(text)',
            1,
        ),
        "CHECK:常驻通知的标题由调用方给",
    ),
    (
        "常驻那两句不问当前角色，直接按司机算",
        SVC,
        lambda s: s.replace(
            "val (title, notice) = NewOrderAlert.serviceNotice(role)",
            "val (title, notice) = NewOrderAlert.serviceNotice(Role.DRIVER)",
            1,
        ),
        "CHECK:常驻那两句按当前角色算",
    ),
    (
        "渠道名改回「后台接收派单」（货主也看得见）",
        CENTER,
        lambda s: s.replace('"后台接收消息",', '"后台接收派单",', 1),
        "CHECK:渠道名不再写死成派单",
    ),
    (
        "渠道描述写死成派单",
        CENTER,
        lambda s: s.replace(
            'description = "关闭 App 后仍在接收消息的常驻提示"',
            'description = "后台接收派单的常驻提示"',
            1,
        ),
        "CHECK:渠道描述角色中性",
    ),
    (
        "设置页那一档的标题写死成收单",
        SETTINGS,
        lambda s: s.replace("title = backgroundRow.first,", 'title = "关掉 App 也收单",', 1),
        "CHECK:设置页那一档的标题按角色说",
    ),
    (
        "设置页的副标题写死成「才收得到新派单」",
        SETTINGS,
        lambda s: s.replace(
            "backgroundRow.second",
            '"关闭后只有打开 App 时才收得到新派单"',
            1,
        ),
        "CHECK:设置页的副标题也按角色说",
    ),
    (
        "设置页那一档其余角色那支被改成司机版（收单）",
        ALERT,
        lambda s: s.replace(
            'AlertKind.REVOKED, null -> "关掉 App 也收消息" to "关闭后只有打开 App 时才收得到新消息"',
            'AlertKind.REVOKED, null -> "关掉 App 也收单" to "关闭后只有打开 App 时才收得到新派单"',
            1,
        ),
        "GRADLE:testEmuDebugUnitTest",
    ),
    (
        "状态那一行关掉后台时不再提「仅前台接收」（司机以为关掉也收得到）",
        ALERT,
        lambda s: s.replace('if (background) "·后台接收" else "·仅前台接收"', 'if (background) "·后台接收" else ""', 1),
        "GRADLE:testEmuDebugUnitTest",
    ),
    (
        "货主那一支的摘要恒写「后台接收中」（后台其实关着）",
        ALERT,
        lambda s: s.replace(
            'if (!hasVoice(role)) return if (background) "后台接收中" else "仅前台接收"',
            'if (!hasVoice(role)) return "后台接收中"',
            1,
        ),
        "CHECK:货主那一支的摘要",
    ),
    (
        "派单员那句被改成司机那句（司机的话出现在两支里）",
        ALERT,
        lambda s: s.replace(
            'AlertKind.PENDING_ORDER -> "SOrders 正在后台接收新订单" to "有新订单待派单会立刻提醒你"',
            'AlertKind.PENDING_ORDER -> "SOrders 正在后台接收派单" to "有新派单会立刻提醒你"',
            1,
        ),
        "CHECK:常驻通知里司机那句只出现一次",
    ),
    (
        "常驻服务把角色写死成司机（不问会话缓存）",
        SVC,
        lambda s: s.replace('val role = Role.fromKey(container.tokenStore.cachedRole() ?: "")', "val role = Role.DRIVER", 1),
        "CHECK:AlertService 把当前角色递进去",
    ),
    (
        "回归用例被改名（那条缺省的用例不见了）",
        KTEST,
        lambda s: s.replace(CLASS, "`_所有角色都默认后台常驻`", 1),
        "CHECK:回归用例里有「所有角色都默认后台常驻」",
    ),
]


def read_src(p: Path) -> tuple[str, bool]:
    data = p.read_bytes()
    return data.decode("utf-8").replace("\r\n", "\n"), b"\r\n" in data


def write_src(p: Path, text: str, crlf: bool) -> None:
    data = text.replace("\r\n", "\n")
    if crlf:
        data = data.replace("\n", "\r\n")
    p.write_bytes(data.encode("utf-8"))


def run_judge() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(JUDGE)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def run_gradle() -> tuple[int, str]:
    p = subprocess.run(
        ["cmd", "/c", str(GRADLE), "-p", "android", ":app:testEmuDebugUnitTest"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def run_all() -> int:
    fails: list[str] = []
    code, out = run_judge()
    if code != 0:
        print("❌ 前提不成立：源码完好时判据脚本就没过")
        print(out[-1500:])
        return 1
    if not GRADLE.exists():
        print(f"❌ 找不到 gradle：{GRADLE}")
        return 1
    code, out = run_gradle()
    if code != 0:
        print("❌ 前提不成立：源码完好时 Android 单测就没过")
        print(out[-1500:])
        return 1
    print("✅ 前提：源码完好时判据脚本与 Android 单测都是绿的")

    touched = sorted({rel for _l, rel, _m, _n in CASES})
    originals = {rel: (ROOT / rel).read_bytes() for rel in touched}
    crlfs = {rel: b"\r\n" in originals[rel] for rel in touched}

    for label, rel, mutate, node in CASES:
        path = ROOT / rel
        plain = originals[rel].decode("utf-8").replace("\r\n", "\n")
        mutated = mutate(plain)
        if mutated == plain:
            fails.append(f"{label}：注入没生效（锚点变了，请更新本脚本）")
            print(f"  [SKIP] {label}")
            continue
        try:
            write_src(path, mutated, crlfs[rel])
            if node.startswith("CHECK:"):
                jcode, jout = run_judge()
                expect = node.split(":", 1)[1]
                hit = jcode != 0 and any("[FAIL]" in ln and expect in ln for ln in jout.splitlines())
            elif node.startswith("GRADLE:"):
                gcode, gout = run_gradle()
                hit = gcode != 0
                if not hit:
                    print("      （gradle 竟然绿了）" + gout.strip().splitlines()[-1][:160])
            else:
                tcode, _tout = run_test(node)
                hit = tcode != 0
        finally:
            path.write_bytes(originals[rel])
        kind = "判据" if node.startswith("CHECK:") else ("Android 单测" if node.startswith("GRADLE:") else "回归测试")
        if hit:
            print(f"  [OK] {label} → {kind}报红")
        else:
            fails.append(f"{label}：注入之后**没有任何检查报红**（修复没有被钉住）")
            print(f"  [MISS] {label} → 全绿")

    dirty = [rel for rel in touched if (ROOT / rel).read_bytes() != originals[rel]]
    if dirty:
        fails.append("跑完没逐字节还原：" + "、".join(dirty))
        for rel in dirty:
            (ROOT / rel).write_bytes(originals[rel])
        print("⚠️  已强制还原：" + "、".join(dirty))
    else:
        print(f"✅ 还原检查：{len(touched)} 个被碰过的文件与运行前逐字节一致")

    print("⚠️  Android 单测结果目录刚被那几条注入污染过 —— 提交前重跑一次 "
          "`_agent/gradle/gradle-8.9/bin/gradle.bat -p android :app:testEmuDebugUnitTest`，"
          "否则 `_tools/qa/_android_test_count.py` 会读到 failures>0。")

    print()
    if fails:
        print("❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"✅ {len(CASES)} 条注入都证明 CHG-0030 的修复真的被钉住了。")
    return 0


def main() -> int:
    lock_reverse_verify()
    try:
        return run_all()
    finally:
        unlock_reverse_verify()


if __name__ == "__main__":
    sys.exit(main())