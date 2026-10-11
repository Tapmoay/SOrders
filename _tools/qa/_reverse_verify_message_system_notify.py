#!/usr/bin/env python
"""反向验证「消息中心的消息在软件外也弹系统通知栏」（FEAT-0027）那一节判据**真的会红**。

### 为什么这一节特别需要反向验证
这一节的判据全是**静态**断言（渠道分了三条、去重那一句在、前台判断接了、extras 带上了、
摘要那一支还在、路由只有一句转发）。静态断言最容易变成一排恒真的字符串匹配 —— 而它守的东西
恰恰是"坏了没人看得出来"的那种：少弹一次、弹两次、点通知去了空页、一次来十条刷屏，
用户那头的表现都只是「这次没收到」或「收到了两条」。

所以每一条都要证明：**把它写坏，判据会红**。

R4-BOUNDARY-JUSTIFICATION: 这份反验不需要任何运行期边界就能说明白 —— 它注入的全是
"同一句话在不在源码里"：渠道 id 与 importance 是 Android 侧的常量对、去重那一句是纯函数里的一行、
前台判断是 Application 生命周期的一个布尔、extras 是三个 putExtra、摘要与路由各是一句。
后端契约与类型系统对这些**一个字都说不了**（它们看不见客户端弹不弹、点去哪），
唯一能证明"判据有牙"的办法就是把它们逐个写坏，看判据变不变红。

用法：python _tools/qa/_reverse_verify_message_system_notify.py    # 全部报红 → 退出码 0
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_message_system_notify.py"

CORE = ROOT / "android/app/src/main/java/com/tapmoay/sorders/core"
SRC = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
NOTIFY = CORE / "NotifyCenter.kt"
MSG = CORE / "MessageNotify.kt"
HUB = CORE / "RealtimeHub.kt"
APP = SRC / "SOrdersApp.kt"

# (说明, 文件, 原文, 替换成, 期望变红的检查名关键词)
MUTATIONS = [
    (
        "不做 id 去重（socket 与回补两条链各弹一格，同一条消息弹两次）",
        MSG,
        "        if (isDuplicate(seen, id)) return false",
        "        if (false) return false",
        "同一条通知（按 id）只弹一次",
    ),
    (
        "去掉前台判断（用户正在看这个 App，通知栏又弹一条）",
        MSG,
        "        if (foreground) return false",
        "        if (false) return false",
        "App 在前台时不弹",
    ),
    (
        "去掉「消息进通知栏」开关（用户关掉了照样弹）",
        NOTIFY,
        "                enabled = prefs.messageNotifyEnabled,",
        "                enabled = true,",
        "跟随「消息进通知栏」开关",
    ),
    (
        "通知不再带深链（点了只把 App 打开，用户还得自己翻消息中心）",
        NOTIFY,
        "            if (m.route != null) putExtra(EXTRA_MESSAGE_ROUTE, m.route)\n",
        "",
        "深链 extras",
    ),
    (
        "多条不再合并（一次每日扫描同时发 N 条 → N 格通知刷屏）",
        MSG,
        "        else -> MessageBatch.Summary(count = pending.size, risk = highest(pending.map { it.risk }))",
        "        else -> MessageBatch.Single(pending.first())",
        "多条合并成一条摘要",
    ),
    (
        "severity → 重要性写死成 HIGH（公告也弹横幅，分档名存实亡）",
        MSG,
        "        MessageRisk.WARN -> NotifyChannels.MESSAGES_WARN\n        MessageRisk.INFO -> NotifyChannels.MESSAGES_INFO",
        "        MessageRisk.WARN -> NotifyChannels.MESSAGES_ALERT\n        MessageRisk.INFO -> NotifyChannels.MESSAGES_ALERT",
        "severity → 重要性分档",
    ),
    (
        "info 那一档被抬成 HIGH（安静的公告开始弹横幅）",
        NOTIFY,
        "                    NotificationManager.IMPORTANCE_LOW,",
        "                    NotificationManager.IMPORTANCE_HIGH,",
        "info 那一档是 LOW",
    ),
    (
        "通知这条链自己算路由（第二套映射：App 内去 A 页、点通知去 B 页）",
        MSG,
        "    fun routeOf(roleKey: String?, type: String, payload: Map<String, JsonElement>?): String? = noticeRoute(roleKey, type, payload)",
        "    fun routeOf(roleKey: String?, type: String, payload: Map<String, JsonElement>?): String? = if (type.isEmpty()) null else null",
        "复用同一份路由",
    ),
    (
        "回补那条链不带 payload（回补来的消息点了不跳转）",
        HUB,
        "            payload = MessageNotify.payloadOf(map?.get(\"payload\") as? Map<*, *>),",
        "            payload = null,",
        "两条链都带上 severity / type / payload / 角色原文",
    ),
    (
        "Application 里不装前台判定（这个布尔永远是 false → 前台也弹）",
        APP,
        "        com.tapmoay.sorders.core.AppForeground.install(this)\n",
        "",
        "Application 里装一次",
    ),
]


def read_src(path: Path) -> tuple[str, bool]:
    data = path.read_bytes()
    return data.decode("utf-8").replace("\r\n", "\n"), b"\r\n" in data


def write_src(path: Path, text: str, crlf: bool) -> bytes:
    data = text.replace("\r\n", "\n")
    if crlf:
        data = data.replace("\n", "\r\n")
    out = data.encode("utf-8")
    path.write_bytes(out)
    return out


def restore_src(path: Path, text: str, crlf: bool) -> None:
    # 还原**当场核对**：写回后重新读回来逐字节比，对不上就非零退出。
    wrote = write_src(path, text, crlf)
    if path.read_bytes() != wrote:
        print("⛔ 还原后与快照不一致（注入污染了源码树）：" + str(path))
        raise SystemExit(2)


def run_redline() -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(CHECK)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    bad = 0
    code, out = run_redline()
    if code != 0:
        print("❌ 前提不成立：源码完好时判据没过\n" + out[-2000:])
        return 1
    print("✅ 前提：源码完好时这一节判据是绿的")

    for label, path, old, new, expect in MUTATIONS:
        src, crlf = read_src(path)
        if src.count(old) != 1:
            print(f"  [SKIP] {label} —— 原文出现 {src.count(old)} 次，无法唯一替换")
            bad += 1
            continue
        write_src(path, src.replace(old, new), crlf)
        try:
            code, out = run_redline()
            fails = [ln for ln in out.splitlines() if "[FAIL]" in ln]
            hit = code != 0 and any(expect in ln for ln in fails)
            detail = f"红 {len(fails)} 条" + ("" if hit else f"：{[f.strip()[:70] for f in fails[:2]]}")
        finally:
            restore_src(path, src, crlf)
        print(f"  [{'OK' if hit else 'MISS'}] {label} → {detail}")
        if not hit:
            bad += 1

    code, out = run_redline()
    ok = code == 0
    print("  [OK] 还原后判据全绿" if ok else "  [MISS] 还原后判据没恢复")
    bad += 0 if ok else 1

    total = len(MUTATIONS) + 1
    if bad:
        print(f"\n❌ {bad}/{total} 不达标。")
        return 1
    print(f"\n✅ {total}/{total} 都红了：这一节的判据真的在检查。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
