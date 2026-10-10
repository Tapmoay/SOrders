"""FEAT-0018 客户端判据：设备身份（X-Device-Id）与「账号↔设备绑定」的解冻入口。

这一块会怎么悄悄坏掉（编号与下面 c.ok(...) 的标签一一对应）：

1. **设备头没了**：X-Device-Id 全库只在 core/ApiClient.kt 的拦截器里加一处；那一行被删掉之后，
   接口照样 200、界面照样能用 —— 只是后端再也认不出这台设备，风控等于没上线。
2. **每页各写一遍**：某个页面里手写一次 header("X-Device-Id", …)，能编译、能跑，甚至"那一页是好的"，
   但别的接口没有 —— 漏掉哪几个谁也不知道（这正是"统一注入点"要防的事）。
3. **403 那句话被截断/改写**：httpMessage 里 detail 一旦被 take()/replace() 处理，
   「已绑 3 台设备，最早那台要到 …；急用请联系派单员在「账户管理 → 编辑」里解冻」
   就成了一句没法照着做的话（日期与出路都不见了）。
4. **「全部解冻」被拿掉**：司机换手机最常用的一下没了，派单员只能一台一台点；界面不会报错。
5. **没拉到时画成 0 台**：UNKNOWN_DEVICE_COUNT 被 ?: 0 替掉，"还没问过后端"变成"名额空着"，
   派单员会让司机去登录，然后吃一个 403。
6. **读了硬件标识**：有人"顺手"加上 TelephonyManager / Settings.Secure，Android 10+ 上拿不到值，
   还踩了隐私红线（App 是内部派单用的，不该碰这些）。

R4-BOUNDARY-JUSTIFICATION: 这一条**没法用边界消除** —— 「设备头只加在唯一一处」是**源码里出现了几次**
这件事，Kotlin 的类型系统、编译期、后端契约都拦不住第二种写法：在任一页面写
header("X-Device-Id", x) 一样能编译、一样能发出请求，而少加的那个接口只会静默地退化成
"没带设备信息"（不报错、也不影响任何既有判据）。同理 "403 原话被截断" 与 "解冻入口被删" 是**产品口径**
（用户 2026-10-11 要求原话显示 / 司机换手机必须一下点完），只在源码文本里看得见。所以只能拿文本钉住，
再由 _tools/qa/_reverse_verify_device_id_header.py（6 种破坏方式全被抓）证明这些钉子有牙。

用法：python _tools/qa/_check_device_id_header.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "tapmoay" / "sorders"
ANDROID_MAIN = ROOT / "android" / "app" / "src" / "main" / "java"
TEST = ROOT / "android" / "app" / "src" / "test" / "java" / "com" / "tapmoay" / "sorders"
DEVICE = MAIN / "core" / "DeviceId.kt"
CLIENT = MAIN / "core" / "ApiClient.kt"
CONTAINER = MAIN / "core" / "AppContainer.kt"
APP = MAIN / "SOrdersApp.kt"
LOGIN = MAIN / "ui" / "login" / "LoginViewModel.kt"
APIS = MAIN / "data" / "remote" / "api" / "Apis.kt"
DTOS = MAIN / "data" / "remote" / "dto" / "Dtos.kt"
REPO = MAIN / "data" / "repo" / "AppRepository.kt"
SCREEN = MAIN / "ui" / "dispatcher" / "AccountManageScreen.kt"
VM = MAIN / "ui" / "dispatcher" / "AccountManageViewModel.kt"
DEVICE_TEST = TEST / "core" / "DeviceIdTest.kt"
COUNT_TEST = TEST / "ui" / "dispatcher" / "DeviceCountTextTest.kt"
MANIFEST = ROOT / "android" / "app" / "src" / "main" / "AndroidManifest.xml"

# 判据下限：只跑到一半的判据比没有判据更危险（它会绿）。
MIN_ITEMS = 45

# ⛔ 设备身份相关的禁词（Android 6+ 拿不到 / 隐私红线；见 DeviceId.kt 文件头）。
HARDWARE_IDS = [
    "TelephonyManager",
    "getImei",
    "getDeviceId(",
    "ANDROID_ID",
    "Settings.Secure",
    "getMacAddress",
    "WifiInfo",
    "Build.SERIAL",
    "getSerial(",
]


def read(p: Path) -> str:
    if not p.exists():
        raise SystemExit("找不到 " + str(p.relative_to(ROOT)))
    return p.read_text(encoding="utf-8", errors="replace")


def strip_comments(src: str) -> str:
    """去掉注释：判据认的是**代码**。

    为什么需要它：DeviceId.kt 的文件头专门写了"为什么不用 IMEI / MAC / 序列号"
    （把禁用词写下来是**说明**，不是**使用**），Apis.kt 的 KDoc 也会提到头名 ——
    不剥注释的话，B2/C7 会把解释性文字判成违规，而真正违规的代码反而混在里面看不出来。
    """
    return re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", src, flags=re.S))


def slice_fun(src: str, header: str) -> str:
    """抠出一个函数的正文（到**同一层**的下一个成员 / 文档注释为止）。

    ⚠️ 三个坑（都是 `_check_sheet_form_pages.py:95-113` 踩过并写在注释里的）：
    ① 不按行号写死（源码天天在动，写死行号的判据第二次就指到别处）；
    ② 必须切到"下一个同层成员"，一路切到文件尾的话，`load()` 会把后面 `unfreezeDevice()`
       里的 `loadDevices(...)` 一起算进来 —— 于是"进页面不许对每个账号各打一次"这条
       **自己把自己判红**（第一版就是这么错的）；
    ③ 缩进取**整行**行首空白（不是 header 在行内的偏移），且**必须带上 `}` 闭合那个量词**
       （少一个 `}`，`\n {4` 就不是量词了，一个都匹配不上、切片照样跑到文件尾）。
    """
    i = src.find(header)
    if i < 0:
        return ""
    line_start = src.rfind("\n", 0, i) + 1
    indent = len(re.match(r"[ \t]*", src[line_start:]).group(0))
    pat = re.compile(r"\n {" + str(indent) + r"}(?:@Composable|/\*\*|(?:private |internal |suspend )*fun )")
    m = pat.search(src, i + len(header))
    return src[i:m.start()] if m else src[i:]


class Checker:
    def __init__(self) -> None:
        self.total = 0
        self.failed = 0

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        self.total += 1
        if cond:
            return
        self.failed += 1
        print("[FAIL] " + label + ("　—— " + detail if detail else ""))

    def present(self, label: str, text: str, needle: str) -> None:
        self.ok(label, needle in text, "源码里找不到：" + needle[:90])

    def absent(self, label: str, text: str, needle: str) -> None:
        self.ok(label, needle not in text, "源码里不该出现：" + needle[:90])


def main() -> int:
    c = Checker()
    device = read(DEVICE)
    client = read(CLIENT)
    container = read(CONTAINER)
    app = read(APP)
    apis = read(APIS)
    dtos = read(DTOS)
    repo = read(REPO)
    screen = read(SCREEN)
    vm = read(VM)
    manifest = read(MANIFEST)
    device_test = read(DEVICE_TEST)
    count_test = read(COUNT_TEST)

    # ---- A. 设备身份（core/DeviceId.kt）----
    c.ok("A1 DeviceId.kt 不是空壳（≥2000 字符）", len(device) >= 2000, "只有 %d 字符" % len(device))
    c.present("A2 设备身份是独立零件（object DeviceIdentity）", device, "object DeviceIdentity {")
    c.present("A3 头名与后端契约一致（X-Device-Id）", device, 'const val HEADER = "X-Device-Id"')
    c.present("A4 install_id 是 UUID（不读硬件标识）", device, "fun newInstallId(): String = UUID.randomUUID().toString()")
    c.present("A5 长度下限与后端一致（8）", device, "const val ID_MIN = 8")
    c.present("A6 长度上限与后端一致（64）", device, "const val ID_MAX = 64")
    c.present("A7 越界的 id 不发（isValidInstallId）", device, "fun isValidInstallId(raw: String?): Boolean = raw != null && raw.length in ID_MIN..ID_MAX")
    c.present("A8 头取值 = install_id:token，半截值不发", device, 'if (isValidInstallId(installId) && !token.isNullOrBlank()) "$installId:$token" else null')
    c.present("A9 落盘用 App 私有 DataStore（device）", device, 'preferencesDataStore(name = "device")')
    c.present("A10 install_id 的盘键", device, 'stringPreferencesKey("install_id")')
    c.present("A11 token 的盘键", device, 'stringPreferencesKey("device_token")')
    c.present("A12 与登录会话分两个文件（退出登录不该丢设备身份）", device, "退出登录会 `clear()` 掉 session")
    c.present("A13 文件头写清为什么不用硬件标识（IMEI）", device, "IMEI")
    c.present("A14 文件头写清为什么不用硬件标识（MAC）", device, "MAC")
    c.present("A15 注释点名 Android 10+ 拿不到 IMEI", device, "READ_PRIVILEGED_PHONE_STATE")
    c.present("A16 失败重试有节流（60 秒）", device, "const val RETRY_COOLDOWN_MS = 60_000L")
    c.present("A17 注册走后端契约的接口", device, "api.register(DeviceRegisterRequest(installId = installId))")
    c.present("A18 后端回的 device_id 为准", device, "val id = resp.deviceId.takeIf { DeviceIdentity.isValidInstallId(it) } ?: installId")
    c.ok("A19 协程取消原样抛（不被当成注册失败）", device.count("catch (e: CancellationException) {") >= 3, "只出现 %d 次" % device.count("catch (e: CancellationException) {"))
    c.ok("A20 注册失败静默返回 false（不阻塞使用）", "catch (_: Exception) {" in slice_fun(device, "suspend fun ensureRegistered("), "ensureRegistered 里没有兜底 catch")
    c.ok("A21 读盘失败也不拦启动（warmCache 有兜底）", "catch (_: Exception) {" in slice_fun(device, "fun warmCache()"), "warmCache 里没有兜底 catch")

    # ---- B. 隐私红线（清单自己算，防清单过期）----
    kt_files = sorted(ANDROID_MAIN.rglob("*.kt"))
    c.ok("B1 Kotlin 源码清单不是空的（≥100 个文件）", len(kt_files) >= 100, "只扫到 %d 个 .kt" % len(kt_files))
    hits = []
    for p in kt_files:
        body = strip_comments(read(p))
        for word in HARDWARE_IDS:
            if word in body:
                hits.append(p.relative_to(ROOT).as_posix() + " :: " + word)
    c.ok("B2 ⛔ 全库不读硬件标识（IMEI/MAC/序列号/ANDROID_ID）", not hits, "；".join(hits[:4]))
    c.absent("B3 清单里没有 READ_PHONE_STATE 权限", manifest, "READ_PHONE_STATE")

    # ---- C. 统一注入点（全库只许一处）----
    c.present("C1 create 收设备身份参数", client, "deviceId: DeviceId,")
    c.present("C2 拦截器里取头取值", client, "val device = deviceId.headerValue()")
    c.present("C3 缺头时补注册（回调，不在这里直接打接口）", client, "if (device == null) onDeviceIdMissing()")
    c.present("C4 头只在拦截器里加（唯一一处）", client, "if (device != null) header(DeviceIdentity.HEADER, device)")
    c.ok("C5 ApiClient 里设备头只加一次", client.count("header(DeviceIdentity.HEADER") == 1,
         "出现了 %d 次" % client.count("header(DeviceIdentity.HEADER"))
    c.present("C6 注释写明这是全库唯一一处", client, "全库唯一**一处加这个头的地方")
    where = []
    for p in kt_files:
        if "X-Device-Id" in strip_comments(read(p)):
            where.append(p.relative_to(MAIN).as_posix())
    c.ok("C7 ⛔ 头名的字面量只许在 DeviceId.kt 里出现一次（别处抄一份就红）",
         sorted(where) == ["core/DeviceId.kt"], "实际出现在：" + ", ".join(sorted(where)))
    add_header = client.count("header(DeviceIdentity.HEADER") + sum(
        strip_comments(read(p)).count('header("X-Device-Id"') for p in kt_files
    )
    c.ok("C8 ⛔ 全库拼设备头的调用点恰好 1 个", add_header == 1, "找到 %d 个" % add_header)
    c.present("C9 Retrofit 建出设备注册接口", client, "deviceApi = retrofit.create(DeviceApi::class.java),")
    c.present("C10 ApiBundle 里有 deviceApi", client, "val deviceApi: DeviceApi,")
    c.ok("C11 ApiClient.create 的调用点唯一（= AppContainer）",
         sum(read(p).count("ApiClient.create(") for p in kt_files) == 1,
         "全库有 %d 处" % sum(read(p).count("ApiClient.create(") for p in kt_files))
    c.present("C12 容器把补注册接上", container, "onDeviceIdMissing = { ensureDeviceRegistered() },")
    c.present("C13 补注册在后台静默跑（不阻塞界面）", container, "appScope.launch(Dispatchers.IO)")
    c.present("C14 启动时预热缓存", app, "container.deviceId.warmCache()")
    c.present("C15 启动时尽力注册一次", app, "container.ensureDeviceRegistered()")
    c.present("C16 注册端点是公开的 POST devices/register", apis, '@POST("devices/register")')
    c.present("C17 账号设备列表端点", apis, '@GET("users/{userId}/devices")')
    c.present("C18 单台解冻端点", apis, '@POST("users/{userId}/devices/{bindingId}/unbind")')
    c.present("C19 全部解冻端点", apis, '@POST("users/{userId}/devices/unbind-all")')
    c.present("C20 出参 DTO 带 active（历史行不占名额）", dtos, "val active: Boolean = true,")
    c.present("C21 出参 DTO 带最后活跃时间", dtos, '@SerialName("last_seen_at") val lastSeenAt: String? = null,')
    c.present("C22 仓库口子：按账号拉设备", repo, "suspend fun devicesOf(userId: Long) = api.userApi.listDevices(userId)")

    # ---- D. 失败要说人话（403 原话原样透出）----
    http = slice_fun(client, "internal fun httpMessage(")
    c.ok("D1 httpMessage 切片存在", len(http) > 200, "只切到 %d 字符" % len(http))
    c.present("D2 只认中文 detail（英文不甩给用户）", http, r"d.any { it in '\u4e00'..'\u9fa5' }")
    c.present("D3 中文 detail 原样返回（不翻译）", http, "if (zh != null) return zh")
    c.ok("D4 ⛔ 原话不许被截断/改写", not any(k in http for k in ("zh.take(", "zh.drop(", "zh.substring(", "zh.replace(")),
         "出现了解冻提示会被截断的处理")
    c.present("D5 规矩写在注释里（后端中文一律原样透出）", client, "### 规矩：后端自己写的中文一律原样透出")
    c.ok("D6 ⛔ 客户端不自己拼后端那句话（只透传）",
         all("已绑 3 台设备" not in read(p) for p in kt_files),
         "有人在客户端把服务端的话抄/改了一遍")
    c.present("D7 登录失败就是 toApiException 的 message", read(LOGIN), "error = ApiClient.toApiException(e).message")

    # ---- E. 账户管理页：已绑 N/3 台 + 解冻入口 ----
    c.present("E1 上限 3 台（用户口径）", vm, "const val MAX_DEVICES = 3")
    c.present("E2 「还没拉到」是独立哨兵值（⛔ 不是 0）", vm, "const val UNKNOWN_DEVICE_COUNT = -1")
    c.present("E3 文案是纯函数（可单测）", vm, "fun deviceCountText(activeCount: Int): String = when {")
    c.present("E4 没拉到画 --，不画 0", vm, '"已绑 --/$MAX_DEVICES 台"')
    c.present("E5 满了要说清第 4 台怎么办", vm, '"已绑 $activeCount/$MAX_DEVICES 台（已满，第 4 台要等最旧那台失效）"')
    c.present("E6 名额只算在用的", vm, "rows?.count { it.active } ?: UNKNOWN_DEVICE_COUNT")
    c.present("E7 设备行要给人看的时间（UTC→本地）", vm, "fun deviceMeta(binding: DeviceBindingDto, zone: ZoneId = ZoneId.systemDefault()): String {")
    c.present("E8 从没活跃过写「从未」不留空", vm, 'val seen = formatDateTimeFull(binding.lastSeenAt, zone).ifBlank { "从未" }')
    c.present("E9 按需拉取（拉过就用缓存）", vm, "if (!force && devices.containsKey(userId)) return")
    c.present("E10 展开才拉那一个账号", vm, "fun toggleDevices(userId: Long) {")
    c.ok("E11 ⛔ 进页面不许对每个账号各打一次（load() 里没有 loadDevices）",
         "loadDevices(" not in slice_fun(vm, "    fun load() {"), "load() 里出现 loadDevices( 了")
    c.present("E12 解冻一台", vm, "fun unfreezeDevice(u: UserDto, binding: DeviceBindingDto) {")
    c.present("E13 全部解冻", vm, "fun unfreezeAllDevices(u: UserDto) {")
    c.present("E14 解冻成功走本页 snackbar 口径", vm, 'actionResult = "已解冻：设备 …" + deviceShortId(binding)')
    c.present("E15 全部解冻也报一句", vm, 'actionResult = "已全部解冻：" + (rosterPhoneOf(u) ?: u.fullName.ifBlank { u.username })')
    c.present("E16 解冻失败原话画在那一块里", vm, "deviceError = toApiException(e).message")
    c.present("E17 卡片上那一行（已绑 N/3 台）", screen, "private fun AccountDevicesRow(vm: AccountManageViewModel, u: UserDto) {")
    c.present("E18 数字来自按需拉到的表", screen, "deviceCountText(vm.activeDevicesOf(u.id))")
    c.present("E19 设备块（卡片与弹层同一份）", screen, "private fun DeviceBindBlock(vm: AccountManageViewModel, u: UserDto, showHeader: Boolean) {")
    c.present("E20 一台设备一行", screen, "private fun DeviceRow(vm: AccountManageViewModel, u: UserDto, b: DeviceBindingDto) {")
    c.present("E21 「全部解冻」是满宽主按钮（司机换手机最常用）", screen, 'Text("全部解冻（" + active.size + " 台）", fontSize = 15.sp)')
    c.present("E22 单台的解冻按钮", screen, 'AccountAction("解冻", Icons.Default.LockOpen, Color(MgrGreen)) { vm.unfreezeDevice(u, b) }')
    c.present("E23 点全部解冻调 VM", screen, "vm.unfreezeAllDevices(u)")
    c.present("E24 那一块的失败红字（不是页面级错误）", screen, "FormErrorLine(vm.deviceError)")
    sheet = slice_fun(screen, "fun AccountFormSheet(")
    c.present("E25 编辑弹层里有「绑定设备」白卡", sheet, "DeviceBindBlock(vm = vm, u = target, showHeader = true)")
    c.present("E26 只在编辑时出现（新增账号没有 id）", sheet, "vm.editing?.let { target ->")
    c.present("E27 卡片上也挂了那一行", slice_fun(screen, "private fun AccountCard("), "AccountDevicesRow(vm = vm, u = u)")
    c.ok("E28 ⛔ 「解冻」不许进 AccountCard 的动作行（既有判据钉着删除/编辑）",
         'AccountAction("解冻"' not in slice_fun(screen, "private fun AccountCard("),
         "AccountCard 切片里出现了「解冻」，会让 _check_sheet_form_pages.py 变红")
    c.present("E29 单测：设备身份的生成/持久化", device_test, "class DeviceIdTest {")
    c.present("E30 单测：清数据后换一个 id", device_test, "清掉数据（换一块空盘）之后算另一台设备")
    c.present("E31 单测：头拼装边界", device_test, "请求头取值的边界：太少太长或没 token 都不发")
    c.present("E32 单测：文案", count_test, "class DeviceCountTextTest {")
    c.present("E33 单测：没拉到不画 0 台", count_test, "还没拉到时不许画成 0 台")

    if c.total < MIN_ITEMS:
        c.ok("判据下限（%d 条）" % MIN_ITEMS, False, "只跑了 %d 条 —— 判据在空转" % c.total)

    if c.failed:
        print("❌ %d/%d 条不达标" % (c.failed, c.total))
        return 1
    print("✅ 全部 %d 项通过：设备头只在一处加、没注册不发半截值、403 原话不截断、「全部解冻」还在" % c.total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())