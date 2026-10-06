"""红线：**订单详情「创建于」要带年份，而「流转记录」不要**（2026-10-07 用户口述）。

## 由来（用户原话，逐句对着做）

> 订单详情那个信息为什么只有月份和时间啊？它还有**年份**的……我们要的那个就是
> **订单号的下面**……要显示**年份的创建于**是多少多少。
> ……项目那个**流转记录不需要显示年份**。

同一句话里有两个相反的要求，所以这一条判据必须同时钉住两半：

| 位置 | 要什么 | 为什么 |
|---|---|---|
| 订单号下面那行「创建于 …」 | **带年份**（yyyy-MM-dd HH:mm） | 这一行是这张单的出生证，跨年对单时没有年份就没法对 |
| 「流转记录」那几步（下单/派单/司机确认/送达/退货/撤销） | **不带年份**（MM-dd HH:mm） | 同一张单先后走过的几步，年月日都是噪音，一行一条要的是「几点几分」 |
| 两端退货申请列表页 | 不动 | 用户这一句只说订单详情；列表页一屏好几条，年份会把行撑长 |

## 这条判据守的事，坏起来一句报错都没有

formatDateTime 与 formatDateTimeFull 的返回类型一样（String），谁用哪一个都编译得过：

| 写坏的方式 | 表现 |
|---|---|
| 「创建于」退回 formatDateTime | 又只剩「09-19 18:09」—— 正是用户点名的那句，别的红线全绿 |
| formatDateTimeFull 的 pattern 写成 MM-dd HH:mm（复制粘贴时忘了改） | 函数在、名字对、调用点也对，**只有年份还是没出来** |
| 流转记录那几条顺手换成带年份那一档 | 用户明确说了不要：一屏 5 行每条都顶着一个年份，把时间挤到右边 |
| 有人「为了统一」把 TimeRow 本体改成带年份 | 上面那条的偷懒版：改一处，流转记录全部跟着变，而详情页里一处 formatDateTimeFull 都没多 |
| 详情页自己再拼一份带年份的格式（take(4) + 年） | 时区换算没了 → 真机上时间错 8 小时（「所有时间早 8 小时」那个缺陷的复发路径） |
| 有人在别的页面（账本 / 退货列表）也顺手用上它 | 用户没说的地方被改了，且没人会去看那几页 |

## R4-BOUNDARY-JUSTIFICATION: 为什么代码边界解决不了这件事

这一条守的是**同一次里两个相反的要求**：同一个时刻，一处要年份、一处不要。类型系统里没有位置
放这个区别 —— 两个函数签名完全同形（(String?, ZoneId) -> String），传错哪一个都能编译、
都能跑、界面都「看着正常」；连单测都不一定红（只有显式断言到年份那一位才红）。
正向的边界（接口 / 分层 / 数据 Owner）在这里同样使不上劲：**这一条不写任何数据、不新增接口**，
能拦住的只有源码结构本身 —— 哪一处**调用**了哪一个函数（下面第 5 组就是那份调用点清单）。

⚠️ 注入式反向验证（改坏 → 本脚本必须红）：_tools/qa/_reverse_verify_order_detail_time.py。

用法：python _tools/qa/_check_order_detail_time.py
"""
from __future__ import annotations

import io
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
#: 剥 Kotlin 注释只有一份实现（抄一份必踩同一个坑）
from _check_pagination_wiring import strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
UTIL = AND / "util/TimeFmt.kt"
DETAIL = AND / "ui/order/OrderDetailScreen.kt"
TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders/util/TimeFmtTest.kt"
CHG = ROOT / "docs/changes/CHG-0066.md"
README = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"
REVERSE = ROOT / "_tools/qa/_reverse_verify_order_detail_time.py"

#: 全仓至少要有这么多 .kt（防「目录被搬走 → 一个都没扫到 → 全绿」）。
MIN_KT = 100
#: 带年份那一档的函数名（唯一一处定义）。
FULL = "fun formatDateTimeFull("
#: 不带年份那一档（流转记录用的还是它）。
SHORT = "fun formatDateTime("
#: 调用点（含定义行：定义那行长这样 `fun formatDateTimeFull(...)`）。
FULL_CALL = "formatDateTimeFull("
#: 闸门：这一行**必须是**带年份那一档（用户说的"订单号的下面"）。
CREATED_GATE = chr(34) + "创建于 " + chr(34) + " + formatDateTimeFull(order.createdAt)"
#: 用户点名的那句（退回老格式就长这样）。
CREATED_OLD = chr(34) + "创建于 " + chr(34) + " + formatDateTime(order.createdAt)"
#: 退货申请块里那两个时刻（同一次里换的，跟着"信息要非常详细"走）。
REQ_TIME_GATE = chr(34) + "申请时间 " + chr(34) + " + formatDateTimeFull(req.createdAt)"
HANDLED_TIME_GATE = "val at = formatDateTimeFull(req.handledAt)"
#: 流转记录那一块：从标题到 TimeRow 的定义为止（TimeRow 本体另有判据钉）。
TIMELINE_A = chr(34) + "流转记录" + chr(34)
TIMELINE_B = "private fun TimeRow("
#: 允许出现带年份那一档的两个文件（其余 .kt 里出现＝顺手改到别处了）。
ALLOWED = {"util/TimeFmt.kt", "ui/order/OrderDetailScreen.kt"}
REQUIRED_FILES = [UTIL, DETAIL, TEST, CHG, README, CLAIM, REVERSE]


def read(p: Path) -> str:
    """读文本并**统一成 LF**（判据里有跨行锚点，CRLF 会让它们一处也匹配不上）。"""
    if not p.exists():
        return ""
    return io.open(p, encoding="utf-8", errors="replace", newline="").read().replace(chr(13) + chr(10), chr(10))


def code(p: Path) -> str:
    return strip_comments(read(p))


def between(text: str, a: str, b: str) -> str:
    """a 之后、b 之前的那一段（用来问「这句在不在这一段里」）。"""
    i = text.find(a)
    if i < 0:
        return ""
    j = text.find(b, i + len(a))
    return text[i : j if j >= 0 else len(text)]


class Checker:
    def __init__(self) -> None:
        self.n_ok = 0
        self.fails: list[tuple[str, str]] = []

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.n_ok += 1
            print(f"  [OK]   {label}")
        else:
            self.fails.append((label, detail))
            print(f"  [!!]   {label}")
            if detail:
                print(f"         {detail}")

    def section(self, title: str) -> None:
        print(f"\n== {title} ==")


def main() -> int:
    c = Checker()
    kts = sorted(AND.rglob("*.kt"))
    codes = {f: code(f) for f in kts}
    util_code = codes.get(UTIL, "")
    detail = read(DETAIL)
    detail_code = codes.get(DETAIL, "")
    test = read(TEST)

    c.section("0. 反空转：文件在、扫得到东西")
    for f in REQUIRED_FILES:
        c.ok("关键文件在：" + f.relative_to(ROOT).as_posix(), f.exists())
    c.ok("全仓 .kt 文件数 ≥ " + str(MIN_KT) + "（防「目录被搬走 → 一条都没扫到 → 全绿」）",
         len(kts) >= MIN_KT, "len=" + str(len(kts)))
    c.ok("TimeFmt.kt 读到了", len(util_code) > 500, "len=" + str(len(util_code)))
    c.ok("订单详情页读到了", len(detail) > 20000, "len=" + str(len(detail)))

    c.section("1. 带年份那一档只有一处定义，且必须是本地时区换算（不是自己拼年份）")
    defs = [(f, codes[f].count(FULL)) for f in kts if FULL in codes[f]]
    c.ok("带年份那一档全仓恰一处定义，且就在 util/TimeFmt.kt",
         len(defs) == 1 and defs[0][1] == 1 and defs[0][0] == UTIL,
         "实际：" + str([(f.relative_to(ROOT).as_posix(), n) for f, n in defs]))
    c.ok("pattern 就是 yyyy-MM-dd HH:mm（复制粘贴时忘了改＝年份根本没出来）",
         'DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm")' in util_code)
    body = between(util_code, FULL, "fun parseBackendInstant(")
    c.ok("它和 formatDateTime 同一条时刻口径：parseBackendInstant + atZoneSameInstant(zone)",
         "parseBackendInstant(iso).atZoneSameInstant(zone)" in body,
         "自己拼的话时区换算就没了 → 真机上时间错 8 小时")
    c.ok("签名逐字（带 zone 参数默认设备时区 —— 测试才能显式传，换台机器不会红绿翻转）",
         "fun formatDateTimeFull(iso: String?, zone: ZoneId = ZoneId.systemDefault()): String {" in util_code)
    c.ok("认不出来的形状退化成截断显示而不是崩（runCatching 与 getOrElse 都在）",
         "runCatching {" in body and ".getOrElse {" in body)
    c.ok("不带年份那一档**还在**（流转记录要靠它，别把它删了）", SHORT in util_code)

    c.section("2. 订单号下面那行「创建于 …」用带年份那一档")
    c.ok("「创建于」用的是带年份那一档（formatDateTimeFull(order.createdAt)）",
         CREATED_GATE in detail_code,
         "用户原话：我们要的那个就是**订单号的下面**……要显示年份的创建于是多少多少")
    c.ok("它没有退回不带年份那一档（退回＝用户报的那句当场复发）",
         CREATED_OLD not in detail_code)

    c.section("3. 「流转记录」仍是老格式（用户明说：不需要显示年份）")
    timeline = between(detail_code, TIMELINE_A, TIMELINE_B)
    c.ok("截到了流转记录那一块（截不到 = 判据失配，先修判据）", len(timeline) > 200,
         "len=" + str(len(timeline)))
    c.ok("流转记录那几步一条不少（TimeRow 调用 ≥5）",
         timeline.count('TimeRow("') >= 5, "n=" + str(timeline.count('TimeRow("')))
    c.ok("那一块里没有一处带年份那一档（用户：项目那个流转记录不需要显示年份）",
         "formatDateTimeFull" not in timeline)
    c.ok("TimeRow 本体仍走不带年份那一档（formatDateTime(iso)）",
         "formatDateTime(iso)" in detail_code,
         "偷懒改这里 = 一处改完流转记录全变，而详情页一处 formatDateTimeFull 都没多")

    c.section("4. 退货申请那块的两个时刻也带年份（同一次里「信息要非常详细」）")
    c.ok("退货申请那两个时刻也带年份（申请时间 ＋ 办理时间）",
         REQ_TIME_GATE in detail_code and HANDLED_TIME_GATE in detail_code,
         "这一块就在同一张详情页上，和「创建于」一起被用户看到的")

    c.section("5. 调用点清单：定义 1 ＋ 订单详情 3，别的 .kt 一处都没有")
    n_full = sum(codes[f].count(FULL_CALL) for f in kts)
    c.ok("调用点清单对得上（定义 1 ＋ 详情页 3 ＝ 4 处）", n_full == 4,
         "实际 " + str(n_full) + " 处：" + str([(f.name, codes[f].count(FULL)) for f in kts if FULL in codes[f]]))
    strays = [f.relative_to(AND).as_posix() for f in kts
              if FULL_CALL in codes[f] and f.relative_to(AND).as_posix() not in ALLOWED]
    c.ok("别的页面一处都没用（用户没说的页面不许跟着改）", strays == [], "多出来的：" + str(strays))
    c.ok("详情页里不带年份那一档还在用（TimeRow 本体那一处；少了＝有人把它也换了）",
         detail_code.count("formatDateTime(") >= 1, "n=" + str(detail_code.count("formatDateTime(")))
    c.ok("调用点算得出来（防「一处都没扫到也算对」）",
         n_full - len(defs) == 3, "n=" + str(n_full - len(defs)))

    c.section("6. 单测钉住了带年份那一档（含跨年翻转）")
    c.ok("单测里并排钉住了两档（同一时刻只差年份）",
         'assertEquals("2026-09-19 18:09", formatDateTimeFull("2026-09-19T10:09:36.713251", shanghai))' in test
         and 'assertEquals("09-19 18:09", formatDateTime("2026-09-19T10:09:36.713251", shanghai))' in test,
         "只断言「更长」是不够的：漏掉时区换算的实现也会更长")
    c.ok("跨年也按本地算（UTC 2025-12-31 20:30 = 东八区 2026-01-01 04:30）",
         '"2026-01-01 04:30"' in test and 'formatDateTimeFull("2025-12-31T20:30:00", shanghai)' in test)

    c.section("7. 文档与反验（归档那一步才算数）")
    chg = read(CHG)
    reverse = read(REVERSE)
    c.ok("CHG-0066.md 在且写够了", len(chg) > 500, "len=" + str(len(chg)))
    for token in ["L-46", "m11305", "创建于", "流转记录", "formatDateTimeFull", "yyyy-MM-dd HH:mm"]:
        c.ok("CHG-0066.md 写了「" + token + "」", token in chg)
    c.ok("README 里登记了 CHG-0066", "[CHG-0066.md](CHG-0066.md)" in read(README))
    c.ok("AI_WORK_CLAIM 里认领了 CHG-0066", "CHG-0066" in read(CLAIM))
    c.ok("反验脚本在、且注入够多（≥8 条）",
         REVERSE.exists() and reverse.count("\n    (\n") >= 8, "n=" + str(reverse.count("\n    (\n")))

    print("\n" + "=" * 60)
    if c.fails:
        print("❌ " + str(len(c.fails)) + " 项不通过：")
        for label, d in c.fails:
            print("   - " + label + (" —— " + d if d else ""))
        return 1
    print("✅ 全部 " + str(c.n_ok) + " 项通过：详情页「创建于」带年份，流转记录不带。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
