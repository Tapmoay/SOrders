# -*- coding: utf-8 -*-
"""后台接收对所有角色都开（2026-10-04 CHG-0030）—— 机器判据。

## 这条是怎么来的

用户 2026-10-04 点名：**消息提醒按角色统一 —— 所有角色后台都能接收，语音只有派单员与司机**。
病灶是一行缺省：`NewOrderAlert.defaultBackground(role)` 从前是 `hasVoice(role)`，于是**货主与批发商**
（没有语音的那两个角色）「后台接收」默认是**关**的，他们「我的 → 消息提醒」那一行写着「仅前台接收」——
关掉 App 之后**一条通知都收不到**，而那些消息对货主是"司机接单了 / 货送到了"。

## 为什么必须有机器的判据

改法看起来只有一行（`= hasVoice(role)` → `= true`），可它牵出四句**按角色说的话**，
每一句都有同一个失败方式：**改回写死、或改回按语音分** —— 编译器一声不响，界面照常渲染，
只有货主会在关掉 App 之后收不到东西：

1. `defaultBackground` 又被写回 `hasVoice(role)`（一行的事，最容易被"顺手改回去"）；
2. 常驻通知那句（`serviceNotice`）又被写死成"正在后台接收派单" —— 它常驻在通知栏里，
   对货主是每天看很多次的一句假话；
3. 设置页那一档（`backgroundRowText`）又只给语音角色写"关掉 App 还收得到什么"；
4. `summary()` 只在语音角色开着的时候才提后台那半句（关掉就一个字不提）。

R4-BOUNDARY-JUSTIFICATION: **为什么代码边界解决不了这件事。**
（⛔ 标记里必须是**ASCII 冒号**：`_check_r3_constraints.py::probe_checker_budget` 认的是
`R3-BOUNDARY-JUSTIFICATION:` / `R4-BOUNDARY-JUSTIFICATION:` 这两个**逐字**字符串。）

"缺省该不该按角色分"不是某一个函数的属性 —— 它是**一条口径落在五个地方**：缺省值、常驻通知那句、
设置页那一档、状态那一行、还有那条**整机共享**的通知渠道名。每一处单看都合法（Kotlin 编译得过、
界面渲染得出来、渠道建得起来），只有把「缺省是不是角色无关」「那几句话里说的是谁的事」放在一起看，
才知道货主关掉 App 之后到底收不收得到东西。类型系统挡不住"把常量改成表达式"这一手。

**反向破坏用例**：`_tools/qa/_reverse_verify_alert_background_all_roles.py` 逐条把修复撤回
（缺省改回 `hasVoice`、常驻通知写死司机那句、设置页只给司机写、状态那一行只在开着时提后台、
渠道名改回"派单"……），每条都要求判据或安卓单测报红，跑完把被碰过的文件**逐字节**还原。
（16 种破坏）

**静默空转保护**：本判据只读源码，锚点少一个就当场报红（`kt_fun` 切段失败 = 正文过短 = 红），
**不做**"找不到就跳过"的软处理；`正在后台接收派单` 这一句还逐处数了**出现次数**
（只许在司机那一支里出现一次）。不碰数据库、不发请求、不改任何文件。

用法：
    python _tools/qa/_check_alert_background_all_roles.py
    python _tools/qa/_check_alert_background_all_roles.py --list
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))

from _airepo import refuse_if_injecting  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
ANDROID = ROOT / "android/app/src/main"
CORE = ANDROID / "java/com/tapmoay/sorders/core"
PROFILE = ANDROID / "java/com/tapmoay/sorders/ui/profile"
ALERT = CORE / "NewOrderAlert.kt"
PREFS = CORE / "AlertPrefs.kt"
SVC = CORE / "AlertService.kt"
CENTER = CORE / "NotifyCenter.kt"
SETTINGS = PROFILE / "AlertSettingsScreen.kt"
KTEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders/core/NewOrderAlertTest.kt"
DOC = ROOT / "docs/changes/CHG-0030.md"
REGISTRY = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"

#: 断言"至少扫到这么多主源码 .kt"—— 防"一个文件都没扫到也算过"。
MIN_KT = 150
#: 回归用例条数下界（实测 37 条；加用例可以，删用例必须同时把这里改小 —— 但请别改）。
MIN_TESTS = 37
#: 改动文档的九节（`_check_dev_spec.py` 对 docs/changes/*.md 提的是同一件事）。
REQUIRED_PARTS = ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨"]


def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def kt_code(src: str) -> str:
    """剥 Kotlin 的散文（`/** … */` 块注释 + 整行 `//` 注释）：判据只许锚在代码上。

    ⚠️ 教训（BUG-0006 判据的第一条假阳性）：函数体里的一句注释把纯子串判断喂饱了。
    """
    out: list[str] = []
    in_block = False
    for ln in src.splitlines():
        s = ln.strip()
        if in_block:
            if "*/" in s:
                in_block = False
            continue
        if s.startswith("/*"):
            if "*/" not in s:
                in_block = True
            continue
        if s.startswith("//"):
            continue
        out.append(ln)
    return "\n".join(out)


_STOPS = ("    /**", "    @", "    fun ", "    private fun ", "}")


def kt_fun(src: str, name: str) -> str:
    """取一个 Kotlin 函数的正文：从 `fun name(` 到下一段 KDoc / 下一个声明 / 文件末的 `}`。

    ⚠️ 切段失败 = 红（不做"找不到就跳过"的软处理）：文件名或函数名被改掉时，
    后面每一条都会「看起来」通过。
    """
    i = src.find("fun " + name + "(")
    if i < 0:
        return ""
    tail = src[i:]
    ends = [tail.find(s, 1) for s in _STOPS]
    ends = [e for e in ends if e > 0]
    return tail[: min(ends)] if ends else tail


class Checker:
    def __init__(self) -> None:
        self.fails = 0
        self.passes = 0

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passes += 1
            print(f"  [OK]   {label}")
        else:
            self.fails += 1
            print(f"  [FAIL] {label}" + (f"\n         → {detail}" if detail else ""))

    def report(self, title: str) -> int:
        print()
        print(f"===== {title} =====")
        print(f"  通过 {self.passes} 项，失败 {self.fails} 项")
        return 1 if self.fails else 0


def section(title: str) -> None:
    print()
    print(f"-- {title} --")


def main() -> int:
    if refuse_if_injecting("后台接收对所有角色都开（CHG-0030）"):
        return 1

    alert = read(ALERT)
    code = kt_code(alert)
    prefs = read(PREFS)
    svc = read(SVC)
    center = read(CENTER)
    settings = read(SETTINGS)
    ktest = read(KTEST)
    doc = read(DOC)
    registry = read(REGISTRY)
    claim = read(CLAIM)

    c = Checker()
    print("后台接收对所有角色都开：语音仍是司机与派单员的活（CHG-0030，2026-10-04）")

    section("零、现场")
    kts = sorted(ANDROID.rglob("*.kt"))
    c.ok(f"扫到 ≥{MIN_KT} 个主源码 .kt", len(kts) >= MIN_KT, f"实测 {len(kts)} 个")
    for name, path in (
        ("NewOrderAlert.kt", ALERT),
        ("AlertPrefs.kt", PREFS),
        ("AlertService.kt", SVC),
        ("NotifyCenter.kt", CENTER),
        ("AlertSettingsScreen.kt", SETTINGS),
        ("NewOrderAlertTest.kt", KTEST),
    ):
        c.ok(f"{name} 在（少一个，下面的锚点全成空谈）", path.exists(), str(path.relative_to(ROOT)))
    c.ok("能切出 defaultBackground 的正文", len(kt_fun(code, "defaultBackground")) > 40, "切不出来 = 函数名被改过")
    c.ok("能切出 serviceNotice 的正文", len(kt_fun(code, "serviceNotice")) > 40)
    c.ok("能切出 backgroundRowText 的正文", len(kt_fun(code, "backgroundRowText")) > 40)
    c.ok("能切出 summary 的正文", len(kt_fun(code, "summary")) > 40)
    tests = ktest.count("@Test")
    c.ok(f"回归用例 ≥{MIN_TESTS} 条（删用例必须同时把 MIN_TESTS 改小）", tests >= MIN_TESTS, f"实测 {tests} 条")

    section("一、缺省：所有角色都开（不跟语音绑）")
    fn = kt_fun(code, "defaultBackground")
    c.ok(
        "后台常驻的缺省对所有角色都开（不再跟 hasVoice 绑）",
        "defaultBackground" in code and "= true" in fn and "hasVoice" not in fn,
        fn.strip()[:160],
    )
    c.ok("那个参数还留着并显式忽略（三个调用点都按角色问）", "@Suppress(\"UNUSED_PARAMETER\")" in code)
    c.ok("AlertPrefs 没设置过时走那条缺省", "else NewOrderAlert.defaultBackground(role)" in prefs)
    c.ok(
        "设置过就以用户的选择为准（contains 那一下问的就是他表过态没有）",
        "if (sp.contains(Keys.BACKGROUND)) sp.getBoolean(Keys.BACKGROUND, false)" in prefs,
    )
    c.ok("AlertPrefs 的注释写清了「没设置过时所有角色都开」", "没设置过时所有角色都开" in prefs);

    section("二、常驻通知：三句话按角色说")
    notice = kt_fun(code, "serviceNotice")
    c.ok("司机那句逐字不动", "\"SOrders 正在后台接收派单\" to \"有新派单会立刻提醒你\"" in notice)
    c.ok("派单员那支说的是新订单", "\"SOrders 正在后台接收新订单\" to \"有新订单待派单会立刻提醒你\"" in notice)
    c.ok(
        "其余角色（货主 / 批发商 / 认不出）那支一个「派单」字都没有",
        "\"SOrders 正在后台接收消息\" to \"有新消息会立刻提醒你\"" in notice,
    )
    c.ok("三支按 voiceKind 分（与语音那套同一口径）", "when (voiceKind(role))" in notice)

    section("三、那条常驻通知本身：标题由调用方给")
    body = kt_fun(center, "serviceNotification")
    c.ok("常驻通知的标题由调用方给（不写死）", ".setContentTitle(title)" in body, body.strip()[:160])
    c.ok("正文也由调用方给", ".setContentText(text)" in body)
    c.ok("NotifyCenter 的注释写明从前写死过", "从前这里写死" in center)

    section("四、渠道（整机共享）：名字与描述不写死成派单")
    c.ok("渠道名是「后台接收消息」", "\"后台接收消息\"" in center)
    c.ok("渠道名不再写死成派单", "\"后台接收派单\"" not in center, "渠道是整机共享的，货主也看得见")
    c.ok("渠道描述角色中性", "关闭 App 后仍在接收消息的常驻提示" in center)
    c.ok("注释点明了「整机共享」这件事", "整机共享" in center)

    section("五、设置页那一档：标题与副标题都按角色说")
    rows = kt_fun(code, "backgroundRowText")
    c.ok("司机那一档说的是收单", "\"关掉 App 也收单\" to \"关闭后只有打开 App 时才收得到新派单\"" in rows)
    c.ok("派单员那一档说的是新订单", "\"关掉 App 也收单\" to \"关闭后只有打开 App 时才收得到新订单\"" in rows)
    c.ok("其余角色那一档说的是收消息", "\"关掉 App 也收消息\" to \"关闭后只有打开 App 时才收得到新消息\"" in rows)
    c.ok("设置页那一档的标题按角色说", "title = backgroundRow.first," in settings)
    c.ok(
        "设置页的副标题也按角色说（不写死「才收得到新派单」）",
        "backgroundRow.second" in settings and "关闭后只有打开 App 时才收得到新派单" not in settings,
    )
    c.ok("运行时那一句原样不动", "正在后台接收（通知栏有一条常驻提示，随时可关）" in settings)
    c.ok("进页面时按角色算首值", "prefs.backgroundEnabled(role)" in settings)

    section("六、常驻服务：角色从会话缓存里读出来")
    s = kt_code(svc)
    c.ok(
        "AlertService 把当前角色递进去（从会话缓存读，不写死司机）",
        "Role.fromKey(container.tokenStore.cachedRole()" in s,
    )
    c.ok("常驻那两句按当前角色算", "NewOrderAlert.serviceNotice(role)" in s)
    c.ok("通知权限没开时那句话还在", "通知权限没开，现在只会在 App 里显示" in s)
    c.ok("类注释已改成角色中性", "后台接收派单的常驻服务" not in svc and "后台接收" in svc)

    section("七、状态那一行：语音与后台两件事都如实写")
    sm = kt_fun(code, "summary")
    c.ok("语音那半句照旧带次数", "\"语音 \" + repeatLabel(repeat, role)" in sm)
    c.ok(
        "后台那半句开着写「后台接收」、关着写「仅前台接收」",
        "if (background) \"·后台接收\" else \"·仅前台接收\"" in sm,
    )
    c.ok(
        "货主那一支的摘要也说后台（不再只说「后台接收中」就算了）",
        "if (!hasVoice(role)) return if (background) \"后台接收中\" else \"仅前台接收\"" in sm,
    )
    c.ok("权限没开还是先说权限", "if (!notificationsAllowed) return \"通知权限未开\"" in sm)
    c.ok("语音被关那一支不动", "if (!voiceEnabled) return \"语音已关\"" in sm)

    section("八、司机那句只许出现在司机那一支")
    n_driver = code.count("\"SOrders 正在后台接收派单\"")
    c.ok("常驻通知里司机那句只出现一次", n_driver == 1, f"实测 {n_driver} 次")
    n_row = code.count("\"关掉 App 也收单\"")
    c.ok("「关掉 App 也收单」按角色出现两次（司机与派单员）", n_row == 2, f"实测 {n_row} 次")

    section("九、回归用例（钉住那条缺省与三句话）")
    c.ok("回归用例里有「所有角色都默认后台常驻」", "`所有角色都默认后台常驻`" in ktest)
    c.ok("回归用例里有「常驻通知按角色说要收的是什么」", "`常驻通知按角色说要收的是什么`" in ktest)
    c.ok("回归用例里有「设置页那一档也按角色说要收的是什么」", "`设置页那一档也按角色说要收的是什么`" in ktest)
    c.ok("回归用例里有「司机的摘要要说清语音和后台两件事」", "`司机的摘要要说清语音和后台两件事`" in ktest)
    c.ok(
        "新用例对非语音角色否定了「派单」（通知与设置页两处）",
        ktest.count("contains(\"派单\")") >= 2,
    )

    section("十、文档与登记")
    c.ok("改动文档在（docs/changes/CHG-0030.md）", "CHG-0030" in doc and "后台" in doc, "文件不存在或缺关键词")
    c.ok("九节齐全（①–⑨）", all(p in doc for p in REQUIRED_PARTS))
    c.ok("文档写清了病灶（defaultBackground 从前按角色分）", "defaultBackground" in doc and "hasVoice" in doc)
    c.ok(
        "文档写清了用户口径（所有角色后台都能接收 / 语音只有派单员与司机）",
        "所有角色" in doc and "语音" in doc,
    )
    c.ok("登记表里有 CHG-0030 行", "| `CHG-0030` |" in registry, "docs/changes/README.md")
    c.ok("认领簿里有 CHG-0030 的块", "CHG-0030" in claim)

    if "--list" in sys.argv:
        print()
        print("  == 它到底在查什么 ==")
        print("  · 缺省：后台接收对所有角色都开（不再跟 hasVoice 绑），用户表过态就以他的选择为准；")
        print("  · 常驻通知：三句话按角色说（司机「派单」逐字不动，货主那支不许出现「派单」）；")
        print("  · 渠道：整机共享的那条叫「后台接收消息」，名字与描述都不写死成派单；")
        print("  · 设置页：那一档的标题与副标题都按角色说，运行时那句原样不动；")
        print("  · 常驻服务：角色从会话缓存读出来再递进去，权限没开那句话还在；")
        print("  · 状态那一行：语音与后台两件事都如实写（关着也要写「仅前台接收」）；")
        print("  · 回归用例 ≥37 条且点到这三句话；改动文档 + 登记表 + 认领簿都在。")

    return c.report("后台接收对所有角色都开（CHG-0030）")


if __name__ == "__main__":
    sys.exit(main())