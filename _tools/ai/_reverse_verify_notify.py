"""反向验证「司机端新单提醒」那一节红线**真的会红**（注入 bug → 必须报错）。

### 为什么这一节特别需要反向验证
这一节的红线全是**静态**断言（清单里有这条权限、渠道建了、素材时长对得上、停止信号接了）。
静态断言最容易变成一排恒真的字符串匹配——而它守的东西恰恰是"坏了没人看得出来"的那种：
权限少一条、常驻通知没人重发、打断之后又补一嗓子，用户那头的表现都只是"这次没响"。

所以每一条都要证明：**把它写坏，红线会红**。

用法：python _tools/ai/_reverse_verify_notify.py    # 全部报红 → 退出码 0
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402

ROOT = repo_root()
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_notify_guardrails.py"

APP = ROOT / "android/app/src/main"
CORE = APP / "java/com/tapmoay/sorders/core"
SRC = APP / "java/com/tapmoay/sorders"
MANIFEST = APP / "AndroidManifest.xml"
GEN = ROOT / "_tools/media/_gen_new_order_clip.py"
VOICE_PROBE = ROOT / "_tools/media/_probe_clip_voice.py"

# (说明, 文件, 原文, 替换成, 期望变红的检查名关键词；None = 只有单测能抓)
MUTATIONS = [
    (
        "少声明通知权限（Android 13+ 上一条通知都发不出去）",
        MANIFEST,
        '    <uses-permission android:name="android.permission.POST_NOTIFICATIONS" />\n',
        "",
        "声明了 POST_NOTIFICATIONS",
    ),
    (
        "MainActivity 退回 standard 启动模式（点通知时 intent 被系统丢掉）",
        MANIFEST,
        '            android:launchMode="singleTop"\n',
        "",
        "singleTop",
    ),
    (
        "少声明震动权限（渠道里的震动模式不生效，静音模式下手机会完全没动静）",
        MANIFEST,
        '    <uses-permission android:name="android.permission.VIBRATE" />\n',
        "",
        "声明了 VIBRATE",
    ),
    (
        "前台服务只留 dataSync（Android 15 上每 24 小时累计 6 小时就被掐）",
        MANIFEST,
        'android:foregroundServiceType="dataSync|specialUse"',
        'android:foregroundServiceType="dataSync"',
        "两种类型",
    ),
    (
        "开机接收器改名（重启手机后再也没人把常驻接收拉起来）",
        MANIFEST,
        'android:name=".core.BootReceiver"',
        'android:name=".core.BootReceiverX"',
        "开机广播接收器已声明",
    ),
    (
        "常驻通知渠道调成高优先级（后台服务变成天天弹横幅的骚扰）",
        CORE / "NotifyCenter.kt",
        "                    NotificationManager.IMPORTANCE_MIN,",
        "                    NotificationManager.IMPORTANCE_HIGH,",
        "常驻通知渠道是 IMPORTANCE_MIN",
    ),
    (
        "订单渠道加系统提示音（响了就停不下来，和语音叠成一片）",
        CORE / "NotifyCenter.kt",
        "                    setSound(null, null)",
        "                    setSound(defaultUri, defaultUri)",
        "订单渠道不出系统提示音",
    ),
    (
        "新增了一个渠道常量但没建渠道（发到不存在的渠道＝什么都不显示）",
        CORE / "NotifyCenter.kt",
        '    const val SERVICE = "service"',
        '    const val SERVICE = "service"\n\n    const val ORPHAN = "orphan"',
        "渠道 ORPHAN",
    ),
    (
        "发通知前不问权限（用户拒过权限时 notify 会抛异常）",
        CORE / "NotifyCenter.kt",
        "    fun postOrder(orderId: Long?, title: String, body: String) {\n        if (!canPost()) return",
        "    fun postOrder(orderId: Long?, title: String, body: String) {\n        if (false) return",
        "发订单通知前问权限",
    ),
    (
        "播放器不再用音频素材（放不出声时只剩 TTS 兜底，素材白放进 APK）",
        CORE / "NewOrderPlayer.kt",
        "MediaPlayer.create(context, clipRes(kind), attrs, AudioManager.AUDIO_SESSION_ID_GENERATE)",
        "MediaPlayer.create(context, R.raw.clip_missing, attrs, AudioManager.AUDIO_SESSION_ID_GENERATE)",
        "取到的素材真的交给了 MediaPlayer",
    ),
    (
        "派单员那条播报偷偷改用司机那份素材（喊的话和要做的事对不上）",
        CORE / "NewOrderPlayer.kt",
        "        AlertKind.PENDING_ORDER -> R.raw.pending_order",
        "        AlertKind.PENDING_ORDER -> R.raw.new_order",
        "[dispatcher] 素材真的被播放器用上了",
    ),
    (
        "派单员那类的时长映射到司机那个常量（重复播报叠在一起）",
        CORE / "NewOrderAlert.kt",
        "        AlertKind.PENDING_ORDER -> PENDING_CLIP_MS",
        "        AlertKind.PENDING_ORDER -> CLIP_MS",
        "派单员那类映射到**它自己**的时长常量",
    ),
    (
        "CLIP_MS 和素材时长对不上（重复播报会叠在一起/每遍之间空一截）",
        CORE / "NewOrderAlert.kt",
        "    const val CLIP_MS = 4874L",
        "    const val CLIP_MS = 1000L",
        "CLIP_MS 与素材实际时长一致",
    ),
    (
        "抬音量的比例被改回 70%（用户明确说过声音小、要 80%）",
        CORE / "NewOrderAlert.kt",
        "    const val BOOST_RATIO = 0.8f",
        "    const val BOOST_RATIO = 0.5f",
        "抬音量的比例是用户要的八成",
    ),
    (
        "档位回到 1/3/5（素材已 5 秒，5 次＝25 秒，从提醒变成吵）",
        CORE / "NewOrderAlert.kt",
        "    val REPEAT_CHOICES = listOf(1, 2, 3, FOREVER)",
        "    val REPEAT_CHOICES = listOf(1, 3, 5, FOREVER)",
        None,  # 纯函数判据：靠单测（默认总时长/档位）
    ),
    (
        "不管什么角色都播（派单员/货主手机上也开始喊「来单了」）",
        CORE / "RealtimeHub.kt",
        "        if (!NewOrderAlert.speaks(role, ev.kind)) return",
        "        if (false) return",
        "播报前问「这一刻该不该响」",
    ),
    (
        "只按角色判、不看事件类型（派单员会对着司机那句「请及时查看」发呆）",
        CORE / "NewOrderAlert.kt",
        "        else -> voiceKind(role) == kind",
        "        else -> hasVoice(role)",
        "「这一刻响不响」按角色 × 类型判",
    ),
    (
        "不再认「order.created」（派单员那张新单永远不响）",
        CORE / "NewOrderAlert.kt",
        '        "order.created" -> AlertEvent(',
        '        "order.created.disabled" -> AlertEvent(',
        "待派单的识别也在纯函数里",
    ),
    (
        "拿那条**没有单号**的角标事件当触发（去重键退化成 pending:-1，第二张单完全不响）",
        CORE / "NewOrderAlert.kt",
        '        "order.created" -> AlertEvent(',
        '        "dispatcher.pending_pool" -> AlertEvent(',
        "没有单号",
    ),
    (
        "派单员那三条「活没了」的信号不再算停止信号（有人接了单他手机还在喊待派单）",
        CORE / "NewOrderAlert.kt",
        '        "order.driver_ack_dispatcher", "order.delivered_dispatcher", "order.cancelled_dispatcher",\n',
        "",
        "停止规则也覆盖派单员的 order.driver_ack_dispatcher",
    ),
    (
        "派单成功后不再打断播报（派完还在喊，他回头去找一张已经派掉的单）",
        SRC / "ui/dispatcher/DispatcherPoolViewModel.kt",
        "                    container.newOrderPlayer.stop()\n",
        "",
        "App 内派单成功后立刻停止播报",
    ),
    (
        "后台常驻的缺省改回「只有司机默认开」（派单员关掉 App 就彻底安静）",
        CORE / "NewOrderAlert.kt",
        "    fun defaultBackground(role: Role?): Boolean = hasVoice(role)",
        "    fun defaultBackground(role: Role?): Boolean = role == Role.DRIVER",
        "后台常驻的缺省按角色算",
    ),
    (
        "设置页的试听改回硬编码司机那句（派单员点试听听到的是别人的活）",
        SRC / "ui/profile/AlertSettingsScreen.kt",
        "                            container.newOrderPlayer.play(\n                                voiceKind,",
        "                            container.newOrderPlayer.play(\n                                AlertKind.NEW_ORDER,",
        "试听播的是**当前角色**那一句",
    ),
    (
        "生成脚本里派单员那份素材的文件名写成司机那份（两句话指向同一个文件）",
        GEN,
        '        "file": "pending_order.wav",',
        '        "file": "new_order.wav",',
        "[dispatcher] PENDING_CLIP_MS 与素材实际时长一致",
    ),
    (
        "生成脚本的默认音色改回云健（男声）——2026-09-21 派单员那句就是这么变成男声的",
        GEN,
        'DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"',
        'DEFAULT_VOICE = "zh-CN-YunjianNeural"',
        "默认音色是用户选的那一个",
    ),
    (
        "音色判据被改坏（阈值抬到 300Hz，女声素材也会被判成男声）",
        VOICE_PROBE,
        "FEMALE_MIN_HZ = 165.0",
        "FEMALE_MIN_HZ = 300.0",
        "两份素材实测都是女声",
    ),
    (
        "不做去重（同一次派单两条链路各响一遍，司机听到两组）",
        CORE / "RealtimeHub.kt",
        "        if (NewOrderAlert.isDuplicate(announced, ev.dedupeKey, now)) return",
        "        if (false) return",
        "播报前查重",
    ),
    (
        "实时事件里不再检查停止信号（撤回/送达后还在喊）",
        CORE / "RealtimeHub.kt",
        # ⚠️ 锚点跟着实现走（2026-09-19 第十四轮）：这一段现在是一个块
        #    （里面多了 `forgetOnStop` —— 撤回后重派要能重新响，见 R14-14），
        #    所以不能再锚"单行 + 尾部语句"。注入的语义不变：**整块拿掉**。
        "                if (NewOrderAlert.shouldStop(e.type)) {\n"
        "                    container.newOrderPlayer.stop()\n",
        "                if (false) {\n"
        "                    container.newOrderPlayer.stop()\n",
        "实时事件里检查停止信号",
    ),
    (
        "点通知后不停止播报（司机已经在看那一单了，手机还在喊）",
        SRC / "MainActivity.kt",
        # ⚠️ 锚点跟着实现走（2026-09-19 报告 R2-NS-3）：`consumeIntent` 现在先过凭据
        #    （`PushTrust.trustedOrderId`）再动手，所以 stop() 不再紧跟 getLongExtra。
        #    注入的语义不变：**把 stop() 那一行删掉**。
        "            container.newOrderPlayer.stop()\n"
        "            container.pendingOrderId.value = orderId",
        "            container.pendingOrderId.value = orderId",
        "点通知立刻停止播报",
    ),
    (
        "App 内接单后不停止播报（接完了还在喊，司机会怀疑接没接上）",
        SRC / "ui/order/OrderDetailViewModel.kt",
        "                container.newOrderPlayer.stop()\n",
        "",
        "App 内接单成功后立刻停止播报",
    ),
    (
        "把取消当成播放失败（打断后又退回 TTS 补喊一句「来单了」）",
        CORE / "NewOrderPlayer.kt",
        "        } catch (e: CancellationException)",
        "        } catch (e: Exception)",
        "取消 ≠ 播放失败",
    ),
    (
        "播报循环用 job?.isActive 判活（UI 线程调用时一次都不播）",
        CORE / "NewOrderPlayer.kt",
        "            while (currentCoroutineContext().isActive) {",
        "            while (job?.isActive == true) {",
        "句柄判活用协程自己的 context",
    ),
    (
        "Socket 负载不再递归转换（站内信的 type/title/单号被整条丢掉）",
        CORE / "SocketManager.kt",
        "        is org.json.JSONArray -> (0 until v.length()).map { plain(v.opt(it)) }\n",
        "",
        "JSONArray 也递归转",
    ),
    (
        "主界面不再对齐后台服务（设置里显示开着、其实服务没起）",
        SRC / "ui/home/RoleHomeScreen.kt",
        "        AlertService.sync(permContext, role)\n",
        "",
        "主界面负责对齐服务状态",
    ),
    (
        "设置页拨开关不再对齐服务（和主界面走两条不同的逻辑）",
        SRC / "ui/profile/AlertSettingsScreen.kt",
        "                    AlertService.sync(context, role)\n",
        "",
        "设置页拨开关复用同一个 sync",
    ),
    (
        "AppRoot 不再消费通知里的单号（点了通知只到首页，还得自己翻那一单）",
        SRC / "ui/nav/NavGraph.kt",
        "            navController.navigate(Routes.orderDetail(id))",
        "            // 注入：不跳转",
        "AppRoot 消费单号并跳转",
    ),
    (
        "「我的」里的消息提醒入口接线被摘掉（点不动了）",
        SRC / "ui/profile/ProfileScreen.kt",
        "onClick = onOpenAlerts,",
        "onClick = null,",
        "「我的」有消息提醒入口且接到了 onOpenAlerts",
    ),
    (
        "共用行组件把 onClick 收下就丢（所有设置行都点不动，界面看着一切正常）",
        SRC / "ui/profile/ProfileRow.kt",
        # ⚠️ 锚点跟着实现走（2026-09-23 静态审计抓到它已经腐烂）：
        #    2026-09-22 用户要求「点一下不要那个水波纹」之后，这一行从单行三元式
        #    改成了多行 + `indication = null` 的 clickable。红线那一侧当时跟着改了锚点，
        #    **这一侧没改** → 从那天起这条注入恒为 SKIP（45 条里少查一条，而没人发现）。
        "            .then(\n"
        "                if (onClick != null) {\n"
        "                    Modifier.clickable(\n"
        "                        interactionSource = remember { MutableInteractionSource() },\n"
        "                        indication = null,\n"
        "                        onClick = onClick,\n"
        "                    )\n"
        "                } else {\n"
        "                    Modifier\n"
        "                },\n"
        "            )",
        "            .then(Modifier)",
        "共用行组件真的把 onClick 接到 clickable 上（不是收下就丢）",
    ),
    (
        "试听按钮改名（用户找不到「确认听得见」的那个按钮）",
        SRC / "ui/profile/AlertSettingsScreen.kt",
        "试听一声",
        "听一下",
        "设置页有试听且真的会播一遍",
    ),
    (
        "撤回也按用户设置重复（连喊五遍「有任务被撤回」，司机以为撤了五单）",
        CORE / "NewOrderAlert.kt",
        "        AlertKind.REVOKED -> AlertPlan(repeats = 1, gapMs = GAP_MS)",
        "        AlertKind.REVOKED -> plan(setting)",
        None,  # 纯函数判据：靠单测
    ),
    # ---- §11：不许承诺「语音播报」而其实不会播（R14-11）----
    (
        "AI 确认卡又承诺「对方会收到语音播报」（安卓侧根本不读 speech_important）",
        SRC / "ai/AiWriteNotificationHandlers.kt",
        'if (important) add("标为重要：只会打上「重要」标记（新版 App 不会因此播语音，仍是普通提醒）")',
        'if (important) add("标为重要：对方会收到语音播报")',
        "凡提到「语音播报」的地方都说明了它会不会发生",
    ),
    (
        "AI 参数名又写「重要（语音播报）」（模型会照着这句向用户承诺）",
        SRC / "ai/AiWrite.kt",
        '"important", "重要标记", kind = AiWriteParamKind.ENUM,',
        '"important", "重要（语音播报）", kind = AiWriteParamKind.ENUM,',
        "凡提到「语音播报」的地方都说明了它会不会发生",
    ),
    (
        "把 AI 层塞进「这么说是对的」豁免表（那层的文案会直接变成承诺）",
        CHECK,
        "SPOKEN_TRUE: dict[str, str] = {\n",
        "SPOKEN_TRUE: dict[str, str] = {\n"
        '    "android/app/src/main/java/com/tapmoay/sorders/ai/AiWrite.kt": "注入：假装 AI 层也可以这么说",\n',
        "AI 层不许进",
    ),
    (
        "把「重要标记不会播语音」这句如实说明整段删掉（不提 ≠ 说清楚了）",
        SRC / "ai/AiWriteNotificationHandlers.kt",
        'if (important) add("标为重要：只会打上「重要」标记（新版 App 不会因此播语音，仍是普通提醒）")',
        "",
        "AI 层「重要标记不播语音」",
    ),
]


def read_src(p: Path) -> tuple[str, bool]:
    data = p.read_bytes()
    return data.decode("utf-8").replace("\r\n", "\n"), b"\r\n" in data


def write_src(p: Path, text: str, crlf: bool) -> bytes:
    data = text.replace("\r\n", "\n")
    if crlf:
        data = data.replace("\n", "\r\n")
    out = data.encode("utf-8")
    p.write_bytes(out)
    return out



def restore_src(p: Path, text: str, crlf: bool) -> None:
    # 还原**当场核对**（R3-07b）：写回后**重新读回来逐字节比**，对不上就非零退出。
    # ⛔ 「写了还原」不是证明；重新读回来的字节 == 刚写出去的字节 才是（L2 要的就是这一句）。
    wrote = write_src(p, text, crlf)
    if p.read_bytes() != wrote:
        print('⛔ 还原后与快照不一致（注入污染了源码树）：' + str(p))
        raise SystemExit(2)

def run(cmd: list[str]) -> tuple[int, str]:
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def run_redline() -> tuple[int, str]:
    return run([sys.executable, str(CHECK)])


def run_tests() -> tuple[int, str]:
    gradle = ROOT / "_agent/gradle/gradle-8.9/bin/gradle.bat"
    r = subprocess.run(
        [str(gradle), "--project-dir", str(ROOT / "android"), ":app:testEmuDebugUnitTest", "--console=plain"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    bad = 0
    code, out = run_redline()
    if code != 0:
        print(f"❌ 前提不成立：源码完好时红线没过\n{out[-1500:]}")
        return 1
    print("✅ 前提：源码完好时这一节红线是绿的")

    for label, path, old, new, expect in MUTATIONS:
        src, crlf = read_src(path)
        if src.count(old) != 1:
            print(f"  [SKIP] {label} —— 原文出现 {src.count(old)} 次，无法唯一替换")
            bad += 1
            continue
        write_src(path, src.replace(old, new), crlf)
        try:
            if expect is None:
                code, out = run_tests()
                hit = code != 0
                detail = "单测报错" if hit else "单测居然还是绿的"
            else:
                code, out = run_redline()
                fails = [ln for ln in out.splitlines() if "[FAIL]" in ln]
                hit = code != 0 and any(expect in ln for ln in fails)
                detail = f"实际红 {len(fails)} 条" + ("" if hit else f"：{[f.strip()[:60] for f in fails[:2]]}")
        finally:
            restore_src(path, src, crlf)
        print(f"  [{'OK' if hit else 'MISS'}] {label} → {detail}")
        if not hit:
            bad += 1

    code, out = run_redline()
    ok = code == 0
    print("  [OK] 还原后红线全绿" if ok else "  [MISS] 还原后红线没恢复")
    bad += 0 if ok else 1

    total = len(MUTATIONS) + 1
    if bad:
        print(f"\n❌ {bad}/{total} 不达标。")
        return 1
    print(f"\n✅ {total}/{total} 都红了：这一节的判据真的在检查。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
