# -*- coding: utf-8 -*-
"""派单时按**路线**自动带价（CHG-0129）—— 路线匹配得上就把钱带出来。

用户 2026-10-15 口述：「运费模板已经绑定了路线，派单时路线匹配就直接带出钱。」
这条需求有四条口径（父会话按用户授权定下），本脚本逐条钉住，少一条就是红：
① 自动带出的只是**默认值**，派单员手一改就以他改的为准（⛔ 不许改完再覆盖回去）；
② 同一条路线命中多条价目时取**最贴近**的那一条，并且**把「选了谁」显示出来**；
③ 匹配不上就**什么也不填**（⛔ 不许猜一个价，更不许拿 0 顶上）；
④ 不许碰「钱只算一处」的既有口径（`backend/app/services/driver_pay.py` 是唯一算司机应得的地方，
   运费模板的钱是**货主运费**，两者不许混）。

R4-BOUNDARY-JUSTIFICATION:
  本脚本只读源码（外加一个既有测试文件的函数名），不跑网络、不连库、不改任何文件。
  为什么非得有它：上面那四条口径**每一条都能被一行改动悄悄地弄丢** ——
  把 return ROUTE_BOUND 改成 ROUTE_TEXT（绑定的路线不再优先）、
  往 usable = [...] 里加一个车型条件（车型偷偷从"只排序"变成"筛子"）、
  删掉在途响应回来时的 if (!shouldOverwriteFreight(...)) return@launch（把人填的数盖回去）、
  删掉平手那半句说明（静默地挑一条）—— 这四种改法**谁都不会红**：
  Kotlin 照样编译、Python 单测只要不覆盖这条路径照样全绿、界面上也看不出来。
  只有把"源码里那句话还在不在"钉住才拦得住，所以每一条都绑在**源码字面量**上
  （不是"有没有这个函数"这种宽判据）。

## 判据（清单全部自己算，不许手写文件列表）
1. 反空转：关键文件在不在；按源码算出来的「参与文件数 / 模块级函数数 / 单测条数」够不够下限；
   少一个文件就先报错并**跳过后面全部判据**（不许安静地绿）。
2. 按 route_id 匹配：价目绑的就是这条路线（route_id 命中）优先于只有终点文字对得上；
   Android 那条路真的把 closest=true 发出去；老调用（不传）语义一字不变。
3. 手改优先：shouldOverwriteFreight(touched) = !touched 只有一处；在途响应回来**再问一次**；
   手改入口唯一（onFreightEdited），手选模板也走它；开一次派单框清掉上一单的手改标记。
4. 多条命中取最贴近：三维排序键（路线 / 分类 / 车型）加"最近改过"；别的分类出局；
   车型只排序不筛；平手必须说出「同样贴近还有 N 条」。
5. 命中显示选了谁：后端那句话点名"取的是哪一条"，接口把它回给界面（why），
   Android 一路带到抽屉里那一行提示；提示行**不写金额**（金额只在可编辑框一处）。
6. 匹配不上不填：后端没挑到就空手回去加一句人话；Kotlin 侧 null（不拿 0 顶上）；
   VM 只写说明不动运费；问不出来也不许说成"这条路线没有价目"。
7. 只读与「钱只算一处」：新服务一个字节都不写库、不 import API 层、不碰 driver_pay.py；
   司机计费那一处里没有这次功能的任何痕迹；自动带价这一段不写订单的运费。

⚠️ 注入式反向验证（改坏 → 本脚本必须红，改回 → 绿）：python _tools/qa/_reverse_verify_route_freight_autofill.py
用法：python _tools/qa/_check_route_freight_autofill.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _check_hints import Checker, strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
ANDROID = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "tapmoay" / "sorders"
KTEST = ROOT / "android" / "app" / "src" / "test" / "java" / "com" / "tapmoay" / "sorders"
BACKEND = ROOT / "backend"

AUTO_SVC = BACKEND / "app" / "services" / "freight_route_autofill.py"
QUOTE_API = BACKEND / "app" / "api" / "v1" / "freight_templates.py"
SCHEMAS = BACKEND / "app" / "schemas" / "freight_template.py"
PY_TEST = BACKEND / "tests" / "test_route_freight_autofill.py"
PRICING_TEST = BACKEND / "tests" / "test_freight_pricing.py"
DRIVER_PAY = BACKEND / "app" / "services" / "driver_pay.py"
KT_PURE = ANDROID / "ui" / "dispatcher" / "FreightAutofill.kt"
KT_TEST = KTEST / "ui" / "dispatcher" / "FreightAutofillTest.kt"
VM = ANDROID / "ui" / "dispatcher" / "DispatcherPoolViewModel.kt"
DIALOG = ANDROID / "ui" / "dispatcher" / "AssignDriverDialog.kt"
DTOS = ANDROID / "data" / "remote" / "dto" / "Dtos.kt"
APIS = ANDROID / "data" / "remote" / "api" / "Apis.kt"
REPO = ANDROID / "data" / "repo" / "AppRepository.kt"

REQUIRED = [AUTO_SVC, QUOTE_API, SCHEMAS, PY_TEST, KT_PURE, KT_TEST, VM, DIALOG, DTOS, APIS, REPO]

# ── 反空转下限（扫描规则或清单坏掉时先喊，不许安静地全绿）────────────────────
MIN_KT_FILES = 3      # 参与自动带价的 Android 主源码文件
MIN_PY_FILES = 2      # 提到 freight_route_autofill 的后端文件
MIN_PY_FUNCS = 8      # 新服务里的模块级函数
MIN_PY_TESTS = 15     # 后端单测条数
MIN_KT_TESTS = 12     # Android 单测条数

C = Checker()


def ok(label: str, cond: bool, detail: str = "") -> None:
    C.ok(label, cond, detail)


def section(title: str) -> None:
    C.section(title)


def read(path: Path) -> str:
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as fh:
        return fh.read()


def src(path: Path) -> str:
    return read(path) if path.is_file() else ""


def ktcode(path: Path) -> str:
    """Kotlin 源码（**剥掉注释**）—— 钉代码时不许被 KDoc 里的说明糊弄过去。"""
    return strip_comments(src(path)) if path.is_file() else ""


def py_body(text: str) -> str:
    """去掉模块 docstring 之后的正文 —— 判"不许写库/不许碰 driver_pay"这类禁令时只看代码。"""
    q = chr(34) * 3
    i = text.find(q)
    if i < 0:
        return text
    j = text.find(q, i + 3)
    if j < 0:
        return text
    return text[j + 3:]


def has_seq(text: str, *parts: str) -> bool:
    """这几段必须**按顺序**出现（中间隔着什么不管）—— 钉"这句话还在不在"。"""
    pos = -1
    for p in parts:
        i = text.find(p, pos + 1)
        if i < 0:
            return False
        pos = i
    return True


def finish() -> int:
    print()
    print("=" * 60)
    if C.fails:
        print("❌ %d 项不通过（通过 %d 项）：" % (len(C.fails), C.n_ok))
        for label, _detail in C.fails:
            print("   - " + label)
        print("_check_route_freight_autofill: %d/%d 通过" % (C.n_ok, C.n_ok + len(C.fails)))
        return 1
    print("✅ 全部 %d 项通过：按 route_id 匹配、手改优先、多条取最贴近并说出来、"
          "匹配不上不填、没碰司机计费的口径。" % C.n_ok)
    print("_check_route_freight_autofill: %d/%d 通过" % (C.n_ok, C.n_ok))
    return 0


def main() -> int:
    # ── 0. 反空转 ──────────────────────────────────────────────────────────
    section("0. 反空转（清单与扫描规则本身得是活的）")
    missing = [str(p.relative_to(ROOT)) for p in REQUIRED if not p.is_file()]
    ok("关键文件都在（后端服务 / 接口 / schema / 后端单测 / Kotlin 纯函数 / 单测 / VM / 抽屉 / DTO / 接口 / 仓库）",
       not missing, "缺：" + "、".join(missing))
    if missing:
        print("❌ 关键文件缺失，后面的判据全部跳过（不许安静地绿）")
        return finish()

    # 清单**自己算**：谁在源码里带了自动带价的痕迹就算参与文件，不手写文件名。
    kt_files = sorted(p for p in (ANDROID / "ui" / "dispatcher").glob("*.kt")
                      if "autoFreight" in src(p) or "自动带价" in src(p))
    py_files = sorted(p for p in BACKEND.rglob("*.py") if "freight_route_autofill" in src(p))
    py_funcs = [ln for ln in py_body(src(AUTO_SVC)).splitlines() if ln.startswith("def ")]
    py_tests = [ln for ln in src(PY_TEST).splitlines() if ln.startswith("def test_")]
    kt_tests = [ln for ln in src(KT_TEST).splitlines() if ln.strip() == "@Test"]
    ok("按源码算出来的 Android 参与文件 = %d 个（下限 %d）：%s"
       % (len(kt_files), MIN_KT_FILES, "、".join(p.name for p in kt_files)),
       len(kt_files) >= MIN_KT_FILES, "扫不到文件说明路径或标记词坏了")
    ok("按源码算出来的后端参与文件 = %d 个（下限 %d）：%s"
       % (len(py_files), MIN_PY_FILES, "、".join(str(p.relative_to(ROOT)) for p in py_files)),
       len(py_files) >= MIN_PY_FILES, "扫不到文件说明路径或标记词坏了")
    ok("新服务里的模块级函数 = %d 个（下限 %d）" % (len(py_funcs), MIN_PY_FUNCS),
       len(py_funcs) >= MIN_PY_FUNCS, "纯函数被搬走/改名了？")
    ok("后端单测 %d 条 / Android 单测 %d 条（下限 %d / %d）"
       % (len(py_tests), len(kt_tests), MIN_PY_TESTS, MIN_KT_TESTS),
       len(py_tests) >= MIN_PY_TESTS and len(kt_tests) >= MIN_KT_TESTS,
       "纯函数没有测试钉着，下次重构就会被顺手改掉")

    auto = src(AUTO_SVC)
    api = src(QUOTE_API)
    schemas = src(SCHEMAS)
    ktp = ktcode(KT_PURE)
    vm = ktcode(VM)
    dialog = ktcode(DIALOG)
    dtos = ktcode(DTOS)
    apis = ktcode(APIS)
    repo = ktcode(REPO)

    # ── 1. 按 route_id 匹配 ────────────────────────────────────────────────
    section("1. 按 route_id 匹配（订单的地点路线 ↔ 价目绑的那条路线）")
    ok("价目绑的就是这条路线（route_id 命中）优先于只有终点文字对得上",
       has_seq(auto, "if fact.route_id is not None and fact.route_id in wish.route_ids:",
               "return ROUTE_BOUND"),
       "这一行被改成 ROUTE_TEXT（或者干脆不看 route_id）时，绑定的路线就不再优先 —— "
       "界面上照样带得出钱，只是带错那一条")
    ok("路线这一维三档齐全（绑上 = 2 / 只有文字 = 1 / 不沾边 = 0）",
       has_seq(auto, "ROUTE_BOUND = 2", "ROUTE_TEXT = 1", "ROUTE_NONE = 0"),
       "三档少一档，route_hit_of 的返回就没人对得上")
    ok("这一单的路线编号来自「地址与联系人」（复用 route_ids_of，不另抄一份）",
       "route_ids=tuple(sorted(route_ids_of(db, addr)))" in auto,
       "各抄一份的后果：同一张价目在待定价页与派单抽屉里算成两条不同的路线")
    ok("不传 closest 时走老路（quote_for），一字不变",
       has_seq(api, "if not closest:",
               "return _quote_out(quote_for(db, order, driver_id=driver_id, category_id=category_id))"),
       "老路是「按司机的规则报价」：条件写反或删掉 = 所有老调用被静默换到新语义")
    ok("closest=true 时按这一单的路线挑（autofill_for 加后端校验过的车型）",
       has_seq(api, "best = autofill_for(", 'vehicle_type=_validate_vehicle(vehicle_type) or "",'),
       "车型不校验的话，前端传一个后端不认识的值整个报价 400（连匹配得上的价都带不出来）")
    ok("Android 派单抽屉真的发 closest=true", has_seq(vm, "closest = true,"),
       "不发的话后端永远走老路（按司机的规则），自动带价一次都不会发生")
    ok("接口上这两个新参数都带默认值（老调用一字不变）",
       has_seq(apis, '@Query("closest") closest: Boolean? = null,',
               '@Query("vehicle_type") vehicleType: String? = null,'),
       "没有默认值 = 别的调用点编译不过；语义上也会把老调用带到新路上")
    ok("仓库层按位置透传这两个新参数",
       ") = api.freightTemplateApi.quoteFreight(orderId, driverId, categoryId, closest, vehicleType)" in repo,
       "漏传参数时界面上永远 closest=null（等于这条功能没接上，而且不报错）")

    # ── 2. 手改优先 ────────────────────────────────────────────────────────
    section("2. 手改优先（自动带出来的只是默认值）")
    ok("手改优先就一行：shouldOverwriteFreight = !touchedByHand",
       "fun shouldOverwriteFreight(touchedByHand: Boolean): Boolean = !touchedByHand" in ktp,
       "写成恒 true = 用户改完还被覆盖（用户 2026-10-15 明确不许）")
    ok("在途响应回来时**再问一次**手改（过期的响应一个字都不许写）",
       has_seq(vm, "if (seq != autoFreightSeq) return@launch",
               "if (!shouldOverwriteFreight(freightTouchedByHand)) return@launch"),
       "网络慢的时候用户已经手填了，这条判断没了就把人填的数盖回自动值")
    ok("手一落笔就记下「这一格是我的了」（freightTouchedByHand = true）",
       has_seq(vm, "fun onFreightEdited(value: String) {", "freightTouchedByHand = true"),
       "没记的话，之后任何一次自动带价都能覆盖用户填的数")
    ok("运费框的改动走 onFreightEdited（不是直接塞 assignFreight）",
       "{ vm.onFreightEdited(InputRules.moneyInput(it)) }," in dialog,
       "直接赋值 = 手改不留下痕迹，下一次自动带价照样覆盖")
    ok("手选模板也走同一条路（手选那一下就是最后拍板）",
       has_seq(vm, "fun applyTemplate(t: FreightTemplateDto) {", "onFreightEdited(t.fee)"),
       "用户 2026-09-19：「同一个路线，我们可以配置多个价格，比如价格一价格二价格三」—— "
       "手选之后被自动值抢回去，等于白选")
    ok("开一次派单框就清掉上一单的手改标记",
       has_seq(vm, "fun openAssign(orderId: Long? = null) {", "freightTouchedByHand = false"),
       "不清的话：上一单被手改过，这一单会**一次都不带价**，而且是静默的")
    ok("已经手改就只写说明、绝不回填（连问都不问）",
       has_seq(vm, "if (!shouldOverwriteFreight(freightTouchedByHand)) {",
               "autoFreightHint = manualHint()", "return"),
       "少了这个提前返回，后面那次请求回来照样会写 assignFreight")

    # ── 3. 多条命中取最贴近 ────────────────────────────────────────────────
    section("3. 同一条路线多条价目：取最贴近的那一条")
    ok("「最贴近」的排序键是三维（路线 / 分类 / 车型），一个都不少",
       "return (-s.route_hit, s.category_hit, s.vehicle_hit)" in auto,
       "少一维 = 同一条路线上「价格一价格二价格三」挑得没有道理可讲")
    ok("三维全平时才轮到「最近改过 → 编号大」（两步稳定排序）",
       has_seq(auto, "ranked = sorted(items, key=lambda s: (s.fact.updated_at, s.fact.template_id), reverse=True)",
               "ranked.sort(key=key_of)"),
       "并在同一个 key 里混升降序很容易写反方向：两步排序才看得出哪一步是主键")
    ok("别的分类的价目直接出局（⛔ 不许拿别类货的价顶上）",
       has_seq(auto, "if int(wish.category_id) in fact.category_ids:", "return CAT_HIT",
               "return CAT_OTHER"),
       "把 CAT_OTHER 改成 CAT_ANY = 别类货的价被当通用价带出来（钱错得静悄悄）")
    ok("车型只参与排序、不参与筛（筛的话「大车司机 + 只写了小车价的路线」会一毛钱都带不出来）",
       "usable = [s for s in on_route if s.category_hit != CAT_OTHER]" in auto,
       "往这一行加一个 s.vehicle_hit != VEH_OTHER 就是拿车型当筛子")
    ok("参选名单里确实没有拿车型当筛子的条件",
       "s.vehicle_hit != VEH_OTHER]" not in auto and "s.vehicle_hit == VEH_OTHER]" not in auto,
       "车型的口径：只用来分先后，不用来淘汰（淘汰的表现是「这条路线一条价都没有」）")
    ok("平手多于一条时必须说出来（发生过一次「最近改过优先」）",
       has_seq(auto, "if best.ties > 1:", "同样贴近还有 {best.ties - 1} 条，按「最近改过」取的"),
       "删掉这半句 = 静默地挑一条；用户看不见「为什么是这个价」")
    ok("平手的条数是真的数出来的（不是写死的 1）",
       "ties = len([s for s in ranked if key_of(s) == key_of(top)])" in auto,
       "写死 1 的话那句说明永远不会出现")
    ok("老路（按司机的规则）的「同档多条不猜」没有被这次改动碰掉",
       "def test_多条同样优先时不猜(" in src(PRICING_TEST),
       "本次只**新增**一条按路线挑的路；老路的歧义语义一动，待定价页就跟着变")

    # ── 4. 命中要显示"选了谁" ─────────────────────────────────────────────
    section("4. 命中之后界面要看得见「选了哪一条、凭什么」")
    ok("后端那句话里点名「取的是哪一条」",
       'head = f"这条路线上一共 {len(best.ranked)} 条价目，取的是「{s.fact.name}」"' in auto,
       "界面**原样显示**这句话（不许自己编），所以名字必须由后端写进去")
    ok("那句话把两条来路分开说（绑了路线 / 只有终点文字对上）",
       has_seq(auto, 'bits.append("价目绑的就是这条路线")',
               'bits.append("路线按终点文字对上（这条价目还没绑路线）")'),
       "只有一条路的时候用户看不出「为什么它比另一条更贴近」")
    ok("接口把 why 回给界面（why=why_text(best)）",
       "why=why_text(best)," in api, "不回的话抽屉里只剩一个光秃秃的数")
    ok("出参里有 why 这一栏（且是空串缺省，老客户端不受影响）",
       has_seq(schemas, "why: str = " + chr(34) * 2), "没有这一栏就没有「选了谁」可以显示")
    ok("Android DTO 也加了 why（缺省空串）",
       has_seq(dtos, "val why: String = " + chr(34) * 2 + ","),
       "少了它 Kotlin 侧读不到这句话")
    ok("Kotlin 那句说明写了「带了哪一条」加「可改」",
       '"已按路线自动带出「" + a.templateName + "」—— 可改，改过之后不再自动覆盖"' in ktp,
       "说明里缺「可改」三个字，用户会以为这价是死的")
    ok("带出价之后把这句话写进提示",
       has_seq(vm, "assignFreight = a.fee", "autoFreightHint = autoHint(a)"),
       "只带钱不写说明 = 用户不知道为什么是这个价")
    ok("抽屉里真的把这一行画出来",
       has_seq(dialog, "if (vm.autoFreightHint.isNotBlank()) {", "vm.autoFreightHint,"),
       "VM 里写了提示但界面不画，等于没显示（这一条只有源码能证明）")
    hint_at = dialog.find("if (vm.autoFreightHint.isNotBlank()) {")
    hint_block = dialog[hint_at:hint_at + 360] if hint_at >= 0 else ""
    ok("提示那一行里没有金额（金额只在上面那个可编辑框里出现一处）",
       bool(hint_block) and "vm.assignFreight" not in hint_block,
       "两处各显各的迟早会对不上；而且那一行是**字**、不是值")

    # ── 5. 匹配不上就什么也不填 ───────────────────────────────────────────
    section("5. 匹配不上就什么也不填（⛔ 不许猜一个价）")
    ok("这一单没有地址就说没地址（不猜路线）",
       'reason="这一单没有送货地址，认不出路线 —— 先在订单里补地址"' in auto,
       "没地址还去比终点文字 = 拿别的单的价顶上")
    ok("这条路线没有价目 → 空手回去加一句人话",
       'reason="这条路线还没有价目 —— 到「运费模板」里给这条线路加一条价"' in auto,
       "这里填 0 或填最近一条的价，都是替用户定了一次价")
    ok("这条路线上的价目都不是这类货的 → 也不填",
       'reason=f"这条路线上的价目都不是「{who}」的 —— 要么给它加一条这类货的价，"' in auto,
       "这一类最容易「顺手拿同路线别的分类的价顶上」")
    ok("接口的 matched 只由 pick 决定（没挑到就是 null）",
       "matched=(None if pick is None else _closest_out(pick.fact))," in api,
       "写成兜底候选 = 界面会把没匹配上也显示成匹配上了")
    ok("Kotlin：没 matched / 金额空白都是 null（不拿 0 顶上）",
       has_seq(ktp, "val m = q?.matched ?: return null", "if (fee.isEmpty()) return null"),
       "拿 0 顶上的后果：用户以为这单 0 元运费，实际上是没匹配上")
    nm_at = vm.find("if (a == null) {")
    nm_end = vm.find("} else {", nm_at)
    nm_block = vm[nm_at:nm_end] if nm_at >= 0 and nm_end > nm_at else ""
    ok("VM：匹配不上只写说明、一个数都不填",
       "autoFreightHint = noMatchHint(q.reason)" in nm_block and "assignFreight" not in nm_block,
       "这一支里只要出现一次 assignFreight = ...，用户看到的就是一个凭空的价")
    ok("说明里明确「运费留空，自己填」（匹配不上与问不出来两种都写了）",
       ktp.count("—— 运费留空，自己填") >= 2,
       "少了这句话，用户会以为「留空」是界面坏了")
    ok("问不出来（断网/超时）也算没匹配上：什么都不填，且不许说成「没有价目」",
       has_seq(vm, "autoFreightHint = failedHint(toApiException(e).message)"),
       "把网络错误说成「这条路线没有价目」是在替后端编结论")

    # ── 6. 钱只算一处 + 只读 ─────────────────────────────────────────────
    section("6. 只读，且没碰「钱只算一处」的口径")
    body = py_body(auto)
    banned = ["db.add(", "db.commit(", "db.flush(", "db.delete(",
              "db.execute(update", "db.execute(delete", "db.execute(insert"]
    hit = [w for w in banned if w in body]
    ok("自动带价这一路只读：一次写库都没有（读也只有 select）",
       not hit and "db.execute(select(" in body,
       "出现了 " + "、".join(hit) + "；落钱仍然只有派单那一个写入口（POST /orders/{id}/assign）")
    imp_lines = [ln.strip() for ln in body.splitlines()
                 if ln.strip().startswith("import ") or ln.strip().startswith("from ")]
    api_imports = [ln for ln in imp_lines
                   if "app.api" in ln or ln.startswith("from app import api")]
    ok("服务层不 import API 层（services 里不许有 from app.api …；注释里提一嘴不算）",
       not api_imports,
       "出现了 " + "；".join(api_imports) + " —— 方向反了：服务层调接口层 = 以后谁也不敢动这两边")
    ok("新服务不碰司机的钱（不 import driver_pay、不算司机应得）",
       "driver_pay" not in body and "pay_for_order" not in body,
       "运费模板的钱是**货主运费**；司机应得只有 backend/app/services/driver_pay.py 一处算")
    dp = src(DRIVER_PAY)
    traces = [w for w in ("freight_route_autofill", "autoFreight", "pick_closest", "closest") if w in dp]
    ok("司机计费那一处（services/driver_pay.py）里没有这次功能的任何痕迹",
       not traces, "出现了 " + "、".join(traces) + "：两条钱的链路被混在一起了")
    tail_at = api.find("    if not closest:")
    closest_block = api[tail_at:] if tail_at >= 0 else ""
    ok("自动带价这一段不写订单的运费（落钱仍然只有派单那一个写入口）",
       bool(closest_block) and "freight_fee" not in closest_block and "db.commit()" not in closest_block,
       "在这一段里顺手把运费落到订单上 = 多出第二个写入口")
    ok("Android 那一份只搬数、不算钱（没有自己乘除或格式化金额）",
       not any(w in ktp for w in ("toDouble(", "BigDecimal", "formatMoney")),
       "界面再算一份的后果是「同一单两个价」，而两边都不报错")

    return finish()


if __name__ == "__main__":
    sys.exit(main())
