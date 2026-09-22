"""「来单提醒」的红线自检（系统通知 + 语音播报 + 后台常驻）。

### 这一节钉的是什么
用户原话（司机端）：「司机端如果派单员派的单给他，他那个要有对应的消息通信还有语音播报
说来，来单了来单了，大概 3 秒钟，可以重复多次，就像是货拉拉的样子」。
用户原话（派单员端，2026-09-21）：「派单员**收到订单的时候**、他**有订单需要派**的时候，
他会有个**语音播报**，就跟我们的司机是一样的」。

⚠️ 2026-09-21 起**这一节是两条线**：司机听「有新派单」（`order.assigned`），
派单员听「有新订单待派单」（`order.created`）。所以判据从"只有司机会响"变成
**「角色 × 事件类型」两维**——只按角色判的话，派单员会对着司机那句话发呆。

这件事有一条**别的功能没有的性质**：它坏了不会报错、不会变红、界面上也看不出来——
用户那头的表现只是「今天没响」。真机验证这一轮就抓到 4 个这种 bug：
1. 站内信的 type/title/content 被静默丢掉（socket 负载只深转了一层，业务层 `as? Map` 拿到 null）；
2. 前台服务的常驻通知在权限刚授予前发出，之后**没有任何人重发**（用户永远看不到）；
3. 「试听一声」在 UI 线程调用时一次都不播（协程在 job 赋值前就同步跑起来了）；
4. 打断播报时会把"取消"当成"播放失败"，于是**退回 TTS 又喊了一嗓子**（司机接了单还在响）。

所以这里把「必须一直成立」的东西钉成断言：权限、渠道、前台服务类型、音频素材时长（两份）、
去重、停止规则、点通知直达。改坏了立刻红。

用法：python _tools/ai/_check_notify_guardrails.py     # 全过 → 退出码 0
"""
import ast
import re
import subprocess
import sys
import wave
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402

ROOT = repo_root()
APP = ROOT / "android/app/src/main"
SRC = APP / "java/com/tapmoay/sorders"
CORE = SRC / "core"
MANIFEST = APP / "AndroidManifest.xml"
GEN = ROOT / "_tools/media/_gen_new_order_clip.py"
VOICE_PROBE = ROOT / "_tools/media/_probe_clip_voice.py"
TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders/core/NewOrderAlertTest.kt"

#: 提到「语音播报」但**说的是真话**的文件 → 为什么这么说不会误导（§11 用）。
#: 每一条都必须能回答"用户看到这句会不会以为某件不会发生的事会发生"。
#: ⚠️ AI 层（`.../ai/`）的文件永远不许进这张表：那层的文案会直接变成对用户的承诺。
SPOKEN_TRUE: dict[str, str] = {
    "android/app/src/main/java/com/tapmoay/sorders/core/NotifyCenter.kt":
        "说的是系统通知渠道的 description（有新派单、任务被撤回时提醒（语音播报由 App 负责））"
        "——陈述的是「渠道本身不出声、语音由 App 自己放」这个事实，"
        "而「新派单/撤回」这一类事件确实有语音（NewOrderPlayer），不是对用户的承诺",
    "android/app/src/main/java/com/tapmoay/sorders/ui/profile/AlertSettingsScreen.kt":
        "这句本身就是**对没有语音的角色（货主）解释他没有语音**：「语音播报只在司机端和派单员端有"
        "（一个要边开车边听单、一个要在手机上派单）；你收到的消息会进通知栏。」"
        "——它出现的前提是 `NewOrderAlert.voiceKind(role) == null`",
    "android/app/src/main/java/com/tapmoay/sorders/ui/profile/ProfileScreen.kt":
        "司机/派单员角色下的副标题「语音播报 / 后台接收新单」，只在 `hasVoice(role)` 为真时显示；"
        "货主走另一半文案（「通知栏提醒 / 后台接收新单」），由 §9 的断言钉着",
}


def read(p: Path) -> str:
    if not p.exists():
        raise SystemExit(f"找不到文件：{p}（改名/移动了？本脚本的断言要跟着改）")
    return p.read_text(encoding="utf-8")


def parse_kinds() -> dict[str, dict[str, str]]:
    """→ 生成脚本里的素材清单（kind → {file, text, const}）。

    ⛔ **清单自己算**：写死"就一个 new_order.wav"的话，加了第二句素材（派单员那句）
    而这里没跟着改，检查会继续绿着说"都对"——本项目栽过 5 次的就是这个形状。
    """
    tree = ast.parse(read(GEN))
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "KINDS":
            return ast.literal_eval(node.value)  # type: ignore[return-value]
    raise SystemExit("生成脚本里找不到 KINDS（改名了？本脚本的素材清单是从它解析出来的）")


def probe_wav(p: Path) -> tuple[int, int, int, int, float, float]:
    """→ (采样率, 声道, 位宽, 毫秒, 开头 1/3 秒峰值, 整段峰值)"""
    import array

    with wave.open(str(p), "rb") as w:
        frames, rate = w.getnframes(), w.getframerate()
        channels, width = w.getnchannels(), w.getsampwidth()
        ms = round(frames * 1000 / rate)
        pcm = w.readframes(frames)
    head = array.array("h")
    head.frombytes(pcm[: rate // 3 * 2])  # 前 1/3 秒（16bit 单声道 = 每采样 2 字节）
    peak_head = max((abs(v) for v in head), default=0) / 32767
    allp = array.array("h")
    allp.frombytes(pcm)
    peak_all = max((abs(v) for v in allp), default=0) / 32767
    return rate, channels, width, ms, peak_head, peak_all


def strip_comments(src: str) -> str:
    """去掉 Kotlin/XML 注释再做匹配。

    为什么必须去注释（这个仓库栽过）：断言 `singleTop` 时，注释里那句
    "launchMode=singleTop 不是可选项" 会让**删掉真代码**的注入照样通过。
    反向验证里的注入同样要改"去注释后的代码"，否则两边一起自欺。
    """
    src = re.sub(r"<!--.*?-->", "", src, flags=re.S)
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"(?m)^\s*//.*$", "", src)
    src = re.sub(r"//[^\n\"']*$", "", src, flags=re.M)
    return src


class Checker:
    def __init__(self) -> None:
        self.fails: list[str] = []
        self.passes = 0

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passes += 1
            print(f"  [OK]   {label}")
        else:
            self.fails.append(label + (f" —— {detail}" if detail else ""))
            print(f"  [FAIL] {label}" + (f" —— {detail}" if detail else ""))

    def present(self, label: str, text: str, pattern: str) -> None:
        m = re.search(pattern, text)
        self.ok(label, m is not None, f"没找到 {pattern!r}")

    def absent(self, label: str, text: str, pattern: str) -> None:
        m = re.search(pattern, text)
        self.ok(label, m is None, f"命中：{m.group(0)!r}" if m else "")


def main() -> int:
    c = Checker()
    manifest = strip_comments(read(MANIFEST))
    realtime = strip_comments(read(CORE / "RealtimeHub.kt"))
    player = strip_comments(read(CORE / "NewOrderPlayer.kt"))
    notify = strip_comments(read(CORE / "NotifyCenter.kt"))
    service = strip_comments(read(CORE / "AlertService.kt"))
    boot = strip_comments(read(CORE / "BootReceiver.kt"))
    socket = strip_comments(read(CORE / "SocketManager.kt"))
    alert = strip_comments(read(CORE / "NewOrderAlert.kt"))
    prefs = strip_comments(read(CORE / "AlertPrefs.kt"))
    home = strip_comments(read(SRC / "ui/home/RoleHomeScreen.kt"))
    main_activity = strip_comments(read(SRC / "MainActivity.kt"))
    nav = strip_comments(read(SRC / "ui/nav/NavGraph.kt"))
    settings = strip_comments(read(SRC / "ui/profile/AlertSettingsScreen.kt"))
    detail_vm = strip_comments(read(SRC / "ui/order/OrderDetailViewModel.kt"))
    pool_vm = strip_comments(read(SRC / "ui/dispatcher/DispatcherPoolViewModel.kt"))
    profile = strip_comments(read(SRC / "ui/profile/ProfileScreen.kt"))
    # 2026-09-21：「我的」页改成共用行组件（`ui/profile/ProfileRow.kt`）之后，
    # "点得动"这件事跨了两个文件，所以下面把它也读进来（判据拆两段，见 §9）。
    profile_row = strip_comments(read(SRC / "ui/profile/ProfileRow.kt"))
    test = read(TEST)

    # ---- §1 权限与清单（少一条，功能就是静默失效） ----
    for perm in (
        "android.permission.POST_NOTIFICATIONS",
        "android.permission.VIBRATE",
        "android.permission.FOREGROUND_SERVICE",
        "android.permission.FOREGROUND_SERVICE_DATA_SYNC",
        "android.permission.FOREGROUND_SERVICE_SPECIAL_USE",
        "android.permission.RECEIVE_BOOT_COMPLETED",
    ):
        c.present(f"清单声明了 {perm.split('.')[-1]}", manifest, re.escape(perm))

    c.present(
        "前台服务声明了两种类型（API 34+ 用 specialUse，29~33 用 dataSync）",
        manifest,
        r'android:name="\.core\.AlertService"[\s\S]{0,200}?foregroundServiceType="dataSync\|specialUse"',
    )
    c.present(
        "specialUse 有子类型说明（Android 14+ 要求）",
        manifest,
        r"PROPERTY_SPECIAL_USE_FGS_SUBTYPE",
    )
    c.present(
        "开机广播接收器已声明（重启手机后要能自己接回来）",
        manifest,
        r'android:name="\.core\.BootReceiver"[\s\S]{0,300}?BOOT_COMPLETED',
    )
    c.present(
        "MainActivity 是 singleTop（standard 下点通知的 intent 会被丢掉）",
        manifest,
        r'android:name="\.MainActivity"[\s\S]{0,200}?android:launchMode="singleTop"',
    )

    # ---- §2 通知渠道：常量与创建必须一一对应（自己算清单，别手写） ----
    # ⚠️ 清单必须从 `object NotifyChannels { … }` 这个块里数：
    #    一开始按整个文件抓 `const val X = "y"`，把 `EXTRA_ORDER_ID = "sorders_order_id"`
    #    也当成了渠道，于是这条判据每次都要人肉分辨"这是不是渠道"——那样的检查早晚被忽略。
    m_block = re.search(r"object NotifyChannels \{([\s\S]*?)\n\}", notify)
    c.ok("找得到 NotifyChannels 块（渠道清单是从这里算的）", m_block is not None)
    channel_consts = re.findall(r'const val ([A-Z_]+) = "([a-z_]+)"', m_block.group(1) if m_block else "")
    c.ok(
        "通知渠道常量至少有 3 个（订单/消息/常驻）",
        len(channel_consts) >= 3,
        f"实际 {len(channel_consts)} 个：{[n for n, _ in channel_consts]}",
    )
    for name, value in channel_consts:
        c.present(
            f"渠道 {name}（{value}）真的被创建",
            notify,
            r"NotificationChannel\(\s*NotifyChannels\." + name + r"\b",
        )
    c.present(
        "订单渠道是 IMPORTANCE_HIGH（否则没有横幅，等于只是个数）",
        notify,
        r"NotificationChannel\(\s*NotifyChannels\.ORDERS[\s\S]{0,120}?IMPORTANCE_HIGH",
    )
    c.present(
        "常驻通知渠道是 IMPORTANCE_MIN（常驻提示不该打扰）",
        notify,
        r"NotificationChannel\(\s*NotifyChannels\.SERVICE[\s\S]{0,120}?IMPORTANCE_MIN",
    )
    c.present(
        "订单渠道不出系统提示音（声音由 App 自己放，才停得下来）",
        notify,
        r"setSound\(null,\s*null\)",
    )
    # 三处发通知（订单/消息/常驻）都必须先问权限：拒了权限时 notify() 会抛 SecurityException
    c.present("发订单通知前问权限", notify, r"fun postOrder[\s\S]{0,400}?canPost\(\)")
    c.present("发普通消息前问权限", notify, r"fun postMessage[\s\S]{0,400}?canPost\(\)")
    c.present("notify() 包了 SecurityException（拒权限不能让 App 崩）", notify, r"catch \(_:\s*SecurityException\)")

    # ---- §3 音频素材：结构、时长、音量都必须和代码里的常量对得上 ----
    # 整段 = 号角（≈1 秒）+ 一整句话（≈3.7 秒）。用户要的是「先响亮的号角，再是一句话，
    # 这句话播 2~3 遍」；号角必须在最前面、够响（他第一句反馈就是「声音比较小」）。
    kinds = parse_kinds()
    c.ok("解析出 >=2 种播报素材（司机那句 + 派单员那句）", len(kinds) >= 2, f"实际 {sorted(kinds)}")
    for key, meta in sorted(kinds.items()):
        clip = APP / "res/raw" / meta["file"]
        c.ok(f"[{key}] 语音素材存在（res/raw/{meta['file']}）", clip.exists(), str(clip))
        if not clip.exists():
            continue
        rate, channels, width, ms, peak_head, peak_all = probe_wav(clip)
        c.ok(f"[{key}] 素材是 24kHz 单声道 16bit（神经语音原生采样率，体积也小）",
             rate == 24000 and channels == 1 and width == 2,
             f"实际 {rate}Hz {channels}ch {width * 8}bit")
        c.ok(f"[{key}] 素材 4~6 秒（号角 + 一整句话）", 4000 <= ms <= 6000, f"实际 {ms}ms")
        c.ok(f"[{key}] 开头 1/3 秒是响亮的号角（峰值 ≥0.5，用户要的就是它抓注意力）",
             peak_head >= 0.5, f"实际峰值 {peak_head:.2f}")
        # 整段也不能削顶：满了会失真，听起来像破音而不是"响亮"
        c.ok(f"[{key}] 整段峰值接近满刻度但不削顶（0.8~1.0）", 0.8 <= peak_all <= 1.0, f"实际 {peak_all:.2f}")
        m = re.search(r"const val " + re.escape(meta["const"]) + r" = (\d+)L", alert)
        c.ok(f"[{key}] 时长常量 {meta['const']} 存在", m is not None)
        if m:
            drift = abs(int(m.group(1)) - ms)
            c.ok(
                f"[{key}] {meta['const']} 与素材实际时长一致（差 >150ms 重复播报会叠在一起）",
                drift <= 150,
                f"常量 {m.group(1)}ms vs 素材 {ms}ms",
            )
    # 素材真的被播放器用上（不是白放进 APK）；两条线各自的素材都要在里面
    for key, meta in sorted(kinds.items()):
        c.present(
            f"[{key}] 素材真的被播放器用上了（R.raw.{meta['file'][:-4]}）",
            player,
            re.escape("R.raw." + meta["file"][:-4]),
        )
    c.present("播放器按类型取素材（不是写死一份）", player, r"private fun clipRes\(kind: AlertKind\)")
    c.present("取到的素材真的交给了 MediaPlayer（取完不用＝素材白放）", player,
              r"MediaPlayer\.create\(context, clipRes\(kind\), attrs")
    c.present("时长也只留一处映射（不是各处自己 when 一遍）", alert, r"fun clipMs\(kind: AlertKind\): Long")
    c.present("派单员那类映射到**它自己**的时长常量（映射错了会叠音）", alert,
              r"AlertKind\.PENDING_ORDER -> PENDING_CLIP_MS")
    c.present("抬音量的比例是用户要的八成", alert, r"const val BOOST_RATIO = 0\.8f")
    c.ok("生成脚本还在（换素材有路可走，不是一次性二进制）", GEN.exists(), str(GEN))
    if GEN.exists():
        gen = read(GEN)
        for key, meta in sorted(kinds.items()):
            c.present(f"[{key}] 生成脚本里有那句话（{meta['text']}）", gen, re.escape(meta["text"]))
        c.present("生成脚本离线时能退回本机 TTS（断网也要能换素材）", gen, r"def _sapi_fallback")
        c.present(
            "生成脚本会打印该改的时长常量（防止换素材忘改常量）",
            gen,
            re.escape("NewOrderAlert.{kind['const']} = {wave_ms}L"),
        )
        c.present("生成脚本按 --kind 选素材与文案（两句各生成各的）", gen, r'ap\.add_argument\("--kind"')
        c.present("生成脚本用神经语音而不是本机 SAPI（「机器人」就是这么来的）", gen, r"import edge_tts")
        # ⛔ 音色必须钉住：**换错音色不报任何错**——文件照样能播、时长照样对得上，
        #    只有用户听得出来。2026-09-21 就是这么出事的：生成派单员那句时用了脚本当时的
        #    默认音色（云健＝男声），而用户 2026-09-17 指定的是**晓晓＝女声**。
        #    两道一起上：① 默认值必须等于用户选的那一个；② 实测基频（下面那句）。
        c.present("生成脚本的默认音色是用户选的那一个（晓晓，女声）", gen,
                  r'DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"')

    voice = subprocess.run(
        [sys.executable, str(VOICE_PROBE)], capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    c.ok(
        "两份素材实测都是女声（拿基频对账，不是看文件名/注释）",
        voice.returncode == 0,
        "；".join(ln.strip() for ln in ((voice.stdout or "") + (voice.stderr or "")).splitlines()
                  if ln.strip().startswith(("❌", "Traceback", "ImportError")))[:200],
    )

    # ---- §4 播报判定：复用纯函数，不许在各处各写一遍 ----
    # ⚠️ 判据是**两维**的（角色 × 事件类型）：只断言"有个角色判断"的话，
    #    把派单员也塞进司机那一句里照样绿——而那正是这一轮最容易写错的地方。
    c.present("两个角色的日常播报各有归属（判定集中在纯函数里）", alert,
              r"fun voiceKind\(role: Role\?\): AlertKind\? = when \(role\) \{[\s\S]{0,200}?Role\.DRIVER -> AlertKind\.NEW_ORDER")
    c.present("派单员那句归派单员（Role.DISPATCHER -> PENDING_ORDER）", alert,
              r"Role\.DISPATCHER -> AlertKind\.PENDING_ORDER")
    c.present("「有没有语音」是算出来的（不给每个调用点各写一遍）", alert,
              r"fun hasVoice\(role: Role\?\): Boolean = voiceKind\(role\) != null")
    c.present("「这一刻响不响」按角色 × 类型判（两维，缺一维就喊错人）", alert,
              r"fun speaks\(role: Role\?, kind: AlertKind\): Boolean[\s\S]{0,400}?voiceKind\(role\) == kind")
    c.present("播报前问「这一刻该不该响」", realtime, r"NewOrderAlert\.speaks\(role, ev\.kind\)")
    c.present("播报前查重（同一次派单后端推两条链路）", realtime, r"NewOrderAlert\.isDuplicate\(")
    c.present("重复次数走设置", realtime, r"NewOrderAlert\.planFor\(")
    c.present("新单/撤回的识别在纯函数里", alert, r'"order\.assigned" -> AlertEvent')
    c.present("待派单的识别也在纯函数里（认 order.created 那条站内信）", alert,
              r'"order\.created" -> AlertEvent')
    c.absent("不用「dispatcher.pending_pool」那条**没有单号**的角标事件当触发（去重键会退化成 -1，第二单完全不响）",
             alert, r'"dispatcher\.pending_pool" -> AlertEvent')
    c.present("「一直响」有止损上限", alert, r"FOREVER_MAX_MS")
    c.present("后台常驻的缺省按角色算（司机与派单员默认开，货主默认关）", alert,
              r"fun defaultBackground\(role: Role\?\): Boolean = hasVoice\(role\)")

    # ---- §5 停止规则：动手的那一方必须能立刻打断 ----
    for ev in ("order.driver_ack", "order.delivered_driver", "order.revoked", "order.cancelled"):
        c.present(f"停止规则覆盖 {ev}", alert, re.escape(f'"{ev}"'))
    # 派单员那条语音的"活没了"信号：后端广播给所有派单员的同形事件
    # （有人接了单 / 已经送达 / 订单被撤销）——对派单员就是"这一单已经有人处理了"。
    for ev in ("order.driver_ack_dispatcher", "order.delivered_dispatcher", "order.cancelled_dispatcher"):
        c.present(f"停止规则也覆盖派单员的 {ev}", alert, re.escape(f'"{ev}"'))
    c.present("实时事件里检查停止信号", realtime, r"NewOrderAlert\.shouldStop\(")
    c.present("App 内接单成功后立刻停止播报", detail_vm, r"driverAck[\s\S]{0,200}?newOrderPlayer\.stop\(\)")
    c.present("App 内派单成功后立刻停止播报（派完还在喊「待派单」＝让他去找一张已派掉的单）",
              pool_vm, r"clearSelection\(\)[\s\S]{0,500}?newOrderPlayer\.stop\(\)")
    c.present("点通知立刻停止播报", main_activity, r"fun consumeIntent[\s\S]{0,600}?newOrderPlayer\.stop\(\)")
    c.present(
        "取消 ≠ 播放失败（否则打断后还会退回 TTS 再喊一句）",
        player,
        r"catch \(e: CancellationException\)[\s\S]{0,200}?throw e",
    )
    c.present("句柄判活用协程自己的 context（UI 线程调用时 job 还没赋值）", player, r"currentCoroutineContext\(\)\.isActive")
    c.absent("播报循环不再用 job?.isActive 判活", player, r"while \(job\?\.isActive")

    # ---- §6 后台常驻：启动时机与开关只有一个真相 ----
    c.present("前台服务启动前先 startForeground", service, r"override fun onStartCommand[\s\S]{0,300}?goForeground\(\)")
    c.present("服务里显式触发实时中枢（App 被服务拉起时界面从没建过它）", service, r"container\.realtimeHub\b")
    c.present("退出登录后服务自己退场", service, r"sessionFlow\.collect[\s\S]{0,300}?stopSelf\(\)")
    c.present("开机后按「登录过 + 用户开着」两个条件才拉起", boot, r"cachedToken\(\) == null\) return[\s\S]{0,200}?backgroundEnabled")
    c.present("主界面负责对齐服务状态", home, r"AlertService\.sync\(permContext, role\)")
    c.present("设置页拨开关复用同一个 sync", settings, r"AlertService\.sync\(context, role\)")
    c.present(
        "已经在跑也要再 start 一次（权限刚授予时那条常驻通知没人重发）",
        service,
        r"fun sync[\s\S]{0,900}?start\(context\)\s*\}",
    )
    c.present("常驻通知文案说清现在收不收得到", service, r"通知权限没开")

    # ---- §7 点通知直达那一单 ----
    c.present("通知带单号 extra", notify, r"putExtra\(EXTRA_ORDER_ID, orderId\)")
    c.present("PendingIntent 指定 IMMUTABLE（targetSdk 31+ 必须）", notify, r"PendingIntent\.FLAG_IMMUTABLE")
    c.present("冷启动读取单号", main_activity, r"consumeIntent\(intent, container, \"onCreate\"\)")
    c.present("热启动（onNewIntent）也读一次", main_activity, r"override fun onNewIntent")
    c.present("AppRoot 消费单号并跳转", nav, r"pendingOrderId[\s\S]{0,400}?navController\.navigate\(Routes\.orderDetail\(id\)\)")

    # ---- §8 Socket 负载必须深转（站内信就是这样被整条丢掉的） ----
    c.present("嵌套 JSONObject 递归转 Map", socket, r"private fun plain\(v: Any\?\)")
    c.present("JSONArray 也递归转", socket, r"is org\.json\.JSONArray ->")
    c.present("站内信内容从 notification 里取", realtime, r'\(n\?\.get\("type"\) as\? String\)')
    c.present("单号从 payload 或顶层取（两处都认）", realtime, r"private fun orderIdOf")

    # ---- §9 设置页与「我的」入口 ----
    # ⚠️ 判据必须钉在**接线上**，不能只找名字：把接线改成空 lambda 之后，
    #    "onOpenAlerts" 这个名字在参数表和导航回调里还在，只找名字的写法照样通过
    #    ——反向验证第一次就是这样漏掉这条注入的。
    # 2026-09-21：「我的」页改成共用行组件（`ProfileRow`）之后，接线跨了两个文件，
    #    所以这条判据拆成**两段，两段都钉在接线代码上**（不比原来那条弱）：
    #      ① 这一页确实把消息提醒那一行接到了 `onOpenAlerts`；
    #      ② 共用行组件真的把 `onClick` 接到了 `clickable` 上（不是收下参数就丢掉）。
    #    ⛔ 只留 ① 会退化成"找名字"（参数收下不装 clickable 也通过）。
    c.present("「我的」有消息提醒入口且接到了 onOpenAlerts", profile, r"onClick = onOpenAlerts")
    c.present("共用行组件真的把 onClick 接到 clickable 上（不是收下就丢）",
              # ⚠️ 锚点认两种写法：2026-09-22 起这一行改成 `indication = null` 的 clickable
              #    （用户要求"点一下不要那个水波纹"），**本意没变**：onClick 必须真的接到
              #    clickable 上、不许收下参数就丢。只认旧写法 → 下次按规范改就平白报红。
              profile_row, r"clickable\(\s*(?:interactionSource[\s\S]{0,140}?)?onClick = onClick")
    c.present("入口右侧显示当前状态（用户不用进去看）", profile, r"fun alertSummary")
    c.present(
        "入口副标题也按角色说（对货主/派单员写「语音播报」＝承诺一件不会发生的事）",
        profile,
        r"语音播报 / 后台接收新单[\s\S]{0,400}?通知栏提醒 / 后台接收新单",
    )
    c.present("摘要按角色说不同的话（货主不该被告知有语音）", alert, r"if \(!hasVoice\(role\)\) return if \(background\)")
    c.present("权限没开时明确说出来（而不是显示一个假的「已开」）", alert, r'"通知权限未开"')
    c.present("设置页在权限没开时给出「去开启」入口", settings, r"手机还没允许 SOrders 发通知[\s\S]{0,400}?openNotificationSettings")
    c.present("设置页能改重复次数", settings, r"REPEAT_CHOICES\.forEach")
    c.present("设置页有试听且真的会播一遍", settings, r"试听一声[\s\S]{0,900}?newOrderPlayer\.play\(")
    # ⚠️ 判据必须钉到**试听那一处调用**（`planFor(voiceKind, repeat)`）：只写 `play(voiceKind,`
    #    的话，开关那一行 `play(voiceKind, NewOrderAlert.plan(1))` 也满足它——反向验证第一次
    #    就是这样漏的（把试听改回写死司机那句，检查照样全绿）。
    c.present("试听播的是**当前角色**那一句（不是写死司机那句）", settings,
              r"container\.newOrderPlayer\.play\(\s*voiceKind,\s*NewOrderAlert\.planFor\(voiceKind, repeat\)")
    c.present("开关文案按角色说（派单员听到的是「待派单」那一句）", settings,
              r"role == Role\.DISPATCHER[\s\S]{0,160}?有新订单待派单")
    c.present("档位文案也按角色说（派单员不接单）", settings, r"repeatLabel\(n, role\)")
    c.present("设置页能跳通知权限设置", settings, r"ACTION_APP_NOTIFICATION_SETTINGS")
    c.present("设置页能跳省电策略设置", settings, r"ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS")
    c.present("设置项落在本机（聊天/设置不上传）", prefs, r'getSharedPreferences\("alerts"')

    # ---- §10 单测：判定逻辑必须有测试（清单自己算） ----
    fns = re.findall(r"fun (\w+)\(", alert)
    public_fns = [f for f in fns if not f.startswith("_")]
    c.ok("纯判定的公开函数 >= 8 个（清单自己从源码里数）", len(public_fns) >= 8, f"实际 {len(public_fns)}")
    missing = [f for f in public_fns if f not in test]
    c.ok("每个公开判定函数都在单测里出现过", not missing, f"没测到：{missing}")

    # ---- §11 全仓库：不许承诺「语音播报」而其实不会播（R14-11，2026-09-19 审计） ----
    # 由来：AI 的确认卡写着「标为重要：对方会收到语音播报」、参数名写着「重要（语音播报）」，
    # 而**安卓侧全仓库没有任何一处读 `speech_important`**（只有旧网页端读）——
    # 于是派单员以为司机手机把这句话喊出来了，实际司机很可能根本没看手机。
    # 原红线 §9 只扫了设置页文案，**没扫 AI 卡片**，所以这类承诺在 AI 层一路绿灯。
    #
    # 判据（**清单自己算**，不手写文件清单）：
    #   ① 把 `android/app/src/main` 下所有 .kt 里的「语音播报」找出来（文件清单由 glob 算）；
    #   ② 每处附近必须有否定词（不会/不播/只在…有/没有）**或**所在文件在下面的 [SPOKEN_TRUE]
    #      里有一条写清理由的豁免（"这句话为什么是真的"）；
    #   ③ 豁免表不许变化石；**AI 层任何文件都不许进豁免表**（那层必须每句都自我否定）。
    kotlin = sorted((APP / "java").rglob("*.kt"))
    c.ok("Kotlin 源码文件 >= 80 个（清单自己算，防路径写错后空转）", len(kotlin) >= 80, f"实际 {len(kotlin)}")
    denied = re.compile(r"不(?:会|播|是|再)|只在|没有|无语音")
    liars: list[str] = []
    seen_files: set[str] = set()
    for p in kotlin:
        rel = str(p.relative_to(ROOT)).replace("\\", "/")
        body = strip_comments(p.read_text(encoding="utf-8"))
        if "语音播报" not in body:
            continue
        seen_files.add(rel)
        if rel in SPOKEN_TRUE:
            continue
        for m in re.finditer(r"语音播报", body):
            window = body[max(0, m.start() - 40) : m.end() + 40]
            if not denied.search(window):
                liars.append(f"{rel}：…{window.strip()[:70]}…")
    c.ok("凡提到「语音播报」的地方都说明了它会不会发生", not liars, "｜".join(liars[:4]))
    fossils = [k for k in SPOKEN_TRUE if k not in seen_files]
    c.ok("「这么说是对的」豁免表没有化石条目", not fossils, "、".join(fossils))
    ai_in_allow = [k for k in SPOKEN_TRUE if "/ai/" in k]
    c.ok("AI 层不许进「语音播报」豁免表（那层每句都必须自我否定）", not ai_in_allow, "、".join(ai_in_allow))
    ai_dir = SRC / "ai"
    # ⚠️ 判据要按**文件**数，不能按出现次数：把卡片里那句删掉之后，
    #    参数说明里还留着两处「语音」，按次数判照样绿（反向验证第一次就是这样漏的）。
    #    真正要成立的是「两处都说清」——模型看到的参数说明 + 用户看到的确认卡。
    #    ⚠️ 标记词必须是"播报"这件事（`播语音|语音播报|语音提醒`），不能是裸的「语音」：
    #    `AiVision.kt` 里那句「embedding / rerank / 语音（模型）收不了图片」是另一码事，
    #    用裸词判会让这条断言永远绿（反向验证第二次就是这样漏的）。
    ai_voice_files = sorted(
        p.name
        for p in ai_dir.glob("*.kt")
        if re.search(r"播语音|语音播报|语音提醒", strip_comments(p.read_text(encoding="utf-8")))
    )
    c.ok(
        "AI 层「重要标记不播语音」在参数说明与确认卡两处都说清了（按文件数，不按出现次数）",
        len(ai_voice_files) >= 2,
        f"只有这些文件把「播报」说清楚了：{ai_voice_files}",
    )

    print("\n" + "=" * 60)
    if c.fails:
        print(f"❌ {len(c.fails)} 项不通过：")
        for f in c.fails:
            print("   - " + f)
        return 1
    print(f"✅ 全部 {c.passes} 项通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
