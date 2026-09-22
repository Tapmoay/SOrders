"""红线：订单详情里的**司机电话**——谁能拨（判据只有一处）、且拨出去的号一定是能拨的。

## 由来（用户 2026-09-22，两轮）

第一轮：
> 「啊加一个功能就是在订单详情的界面当中。**可以拨打司机电话**，这个功能，这个显示啊，
> 这个功能显示**只会在派单端里其他人是没有的**，也就是点击一个**拨号按钮**，它这个自动啊
> **弹到那个拨号界面**然后，它可以拨号打电话给司机。」

第二轮（本轮放宽）：
> 「还有一个就是我们那个呃派单啊……派单员，他是**可以拨打司机电话**的，包括啊或者**批发商
> 也是可以拨打司机电话**的……也就是说，他在那**详情页面**是有个选项的啊，拨打司机电话，
> **只有这两个人能看得到，司机是没有这个的**。」

## 这条规则会被写坏成什么样（每一条都"不报错、不崩"）

| 写坏的方式 | 表现 |
|---|---|
| 把「谁能拨」那道门放开（去掉 `&& dialable` 之外的任何放宽） | 普通货主/司机也多出一颗按钮 —— 用户明说过"只有这两个人"，而没人会为"多了一颗按钮"报错 |
| 在详情页里**就地再写一遍**角色判断（不调 `canDialDriver`） | 判据分叉：以后改口径只改一处，另一处照旧（"批发商不能拨 / 普通货主能拨"同时成立） |
| 判据本体放宽成"所有货主" | 批发商那一档被淹掉，普通货主也拿到动作（放开的是一类权限，不是显示） |
| 判据本体把司机也算进去 | 司机多一颗"打给自己"的按钮（而这一行本来就画给他看） |
| `is_member` 取不到时默认**给** | 一次 `/users/me` 抖动就让普通货主拿到按钮（拿不准的动作就不该递出去） |
| 改用 `ACTION_CALL` | 要 `CALL_PHONE` 权限（没申请 → 点一下**什么都不发生**），有权限则**一碰就拨出去** —— 而"点一下就拨"正是用户禁止的（下单人那一行特意加了确认弹窗） |
| 号码不是能拨的形状时也给按钮 | 司机账号进回收站之后后端会下发 `13800001234_del160`（软删释放号码用的后缀），按钮拨出去是空号，用户以为 App 坏了 |
| 客户端自己写一份电话校验 | 与 `core/InputRules.kt`（全库唯一一份）分叉 → 同一串号码"能填不能拨/能拨不能填" |
| 后端把软删后缀原样下发 | `driver_phone` 落在**拨号按钮**底下才变得危险：用户按下去才知道打不通，那时人已经不在手机旁边 |
| 把按钮整颗删掉（"简化"） | 用户点名要的功能没了，而这一页看起来完全正常 |
| 顺手把整行藏给非派单端 | 用户只说了**按钮**给谁；司机是谁这一行本身三个角色都看（它同时是"这单谁在拉"的记账信息） |
| 改了核心文件（`order_response.py`）却不更新定位表 | 下一个人按地图去读，读到的是"没有这段处理"的那一版 |

## 判据
Android：`ui/common/DriverCall.kt` 是**唯一一份**判据（全源码树里只有一处 `fun canDialDriver(`），
且明说了"普通货主与司机不给"（文件里出现 `Role.DRIVER` 就报红）；`OrderDetailScreen.kt` 的
`DriverRow` 定义与调用、开关真的调它、`ACTION_DIAL`、不可拨就不画、图标与语义色俱在、按钮与信息**同排**；
`OrderDetailViewModel` 提供 `isMemberShipper`（取不到＝不给）。
后端：`services/order_response.py` 下发的 `driver_phone` 过 `strip_del_suffix`（软删后缀去尾）。
配套：单测、后端用例、设计规范 §5 那条偏好、定位表那一行。

⚠️ 注入式反向验证：`_tools/qa/_reverse_verify_order_driver_call.py`（每条都必须能红）。

用法：python _tools/qa/_check_order_driver_call.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
#: 复用兄弟红线里剥注释的实现，不抄第二份。
#: ⚠️ **必须剥注释**：上面那些"⛔ 别改成 ACTION_CALL"的话本身就写在注释里，
#:    不剥的话"代码里没有 ACTION_CALL"这条判据会被自己的注释永远弄红（或被绕过）。
from _check_pagination_wiring import strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
DETAIL = ANDROID / "ui/order/OrderDetailScreen.kt"
DETAIL_VM = ANDROID / "ui/order/OrderDetailViewModel.kt"
DRIVER_CALL = ANDROID / "ui/common/DriverCall.kt"
DRIVER_CALL_TEST = (
    ROOT / "android/app/src/test/java/com/tapmoay/sorders/ui/common/DriverCallTest.kt"
)
INPUT_RULES = ANDROID / "core/InputRules.kt"
ORDER_RESPONSE = ROOT / "backend/app/services/order_response.py"
BACKEND_TEST = ROOT / "backend/tests/test_order_driver_phone.py"
DESIGN = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
LOCATOR = ROOT / "docs/PROJECT_MAP/08_CODE_LOCATOR.md"

#: 调用点那一小段的锚（窗口以它为中心向两边展开）。
CALL_ANCHOR = "val driverPhone = order.driverPhone.orEmpty().trim()"

#: 开关那一行（页面里**唯一**允许出现"谁能拨"的地方＝这一次调用）。
GATE_CALL = "onDial = if (canDialDriver(role, memberShipper) && dialable) {"

#: 这一页把「我是不是批发商」喂给 `DetailBody` 的那一行（会话里没有 `is_member`，只能取一次 `/users/me`）。
MEMBER_WIRE = "memberShipper = vm.isMemberShipper,"


def read(p: Path) -> str:
    if not p.exists():
        raise SystemExit(f"找不到文件：{p}（改名/移动了？本脚本的断言要跟着改）")
    return p.read_text(encoding="utf-8")


def read_code(p: Path) -> str:
    return strip_comments(read(p))


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
        self.ok(label, m is None, f"命中：{m.group(0)[:60]!r}" if m else "")


def main() -> int:
    c = Checker()
    code = read_code(DETAIL)
    raw = read(DETAIL)
    orsp = read_code(ORDER_RESPONSE)
    gate_src = read_code(DRIVER_CALL) if DRIVER_CALL.exists() else ""

    print("== 1. 订单详情：司机那一行的按钮与它的开关 ==")
    n_call = len(re.findall(r"DriverRow\(", code))
    c.ok("`DriverRow` 有定义有调用（正好 2 处：1 定义 + 1 调用）", n_call == 2,
         f"找到 {n_call} 处 —— 多了说明别处也画了一份，少了说明这一行没了")

    # 调用点窗口：从锚点向两边展开（不要把整页都卷进来，"谁能拨"那道门必须在**这一行**上）
    i = code.find(CALL_ANCHOR)
    c.ok("找得到司机那一行的调用点（锚点还在）", i >= 0, f"没找到 {CALL_ANCHOR!r}")
    block = code[max(0, i - 600): i + 1000] if i >= 0 else ""

    c.present("司机这一行**只以『有司机』为条件**（三个角色都画这一行）",
              block, r"if \(!order\.driverName\.isNullOrBlank\(\)\) \{\s*val driverPhone")
    # ⚠️ 拆成三条、别揉成一条：揉起来之后"谁能拨"和"号码不可拨就不给"会互相掩护 ——
    #    去掉 `&& dialable` 时前一条照样绿（`dialable` 这个 val 还在上面算着，只是没人用）。
    c.present("**拨号按钮走的是共用判据**（`ui/common/DriverCall.kt::canDialDriver`，判据只有一处）",
              block, re.escape(GATE_CALL))
    c.present("**号码不是能拨的形状就不给按钮**（`dialable` 真的接进了开关）",
              block, r"onDial = if \(canDialDriver\([^)]*\) && dialable\) \{")
    # ⚠️ "就地再写一遍角色判断"是这条规则最现实的坏法：判据分叉，改一处漏一处。
    # ⚠️ 窗口**只取这一行自己的判断区**（从「有司机吗」那一句起、到拨号动作结束）：上面几行
    #    还有一个 `role == Role.DRIVER || Role.DISPATCHER`（那是**内部备注**给谁看的），
    #    把它卷进来会造成假红 —— 而假红的下场就是下一个人把这条判据删掉。
    # ⚠️ 窗口**不许用 `GATE_CALL` 定位**：把判据换成就地角色判断时那一行就没了，
    #    取不到窗口 → 窗口是空的 → "空串里当然没有 Role" → 这条判据**自己被绕过**（反向验证抓到）。
    row_i = code.find("if (!order.driverName.isNullOrBlank()) {")
    decide_block = code[row_i: row_i + 900] if row_i >= 0 else ""
    c.ok("取到了『司机那一行』的判断区（取不到这条就是空转）",
         len(decide_block) > 300 and "ACTION_DIAL" in decide_block,
         f"{len(decide_block)} 个字符、含拨号动作＝{'ACTION_DIAL' in decide_block}")
    c.absent("页面上**没有**就地写的角色判断（谁能拨只由 `canDialDriver` 回答）",
             decide_block, r"Role\.(DISPATCHER|SHIPPER|DRIVER)")
    c.present("拨号走系统拨号盘（`ACTION_DIAL`）", block, r"android\.content\.Intent\.ACTION_DIAL")
    c.absent("代码里没有 `ACTION_CALL`（它会直接拨出去，还要 CALL_PHONE 权限）",
             block, r"ACTION_CALL")
    c.present("可拨性复用 `InputRules` 那一份（不自己写一份电话规则）",
              block, r"InputRules\.PHONE_MAX[\s\S]{0,200}?InputRules\.phoneError\(")

    print("\n== 2. 「谁能拨」的判据本体（只有一份实现）==")
    c.ok("判据在自己的文件里（`ui/common/DriverCall.kt`）", DRIVER_CALL.exists(),
         f"缺 {DRIVER_CALL.name}")
    # ⚠️ 清单**自己算**（全源码树扫一遍），不手写"该有哪些文件"：手写清单必然过期，
    #    而这里要抓的恰恰是"别处又冒出一份实现"。
    defs = [
        p.relative_to(ROOT).as_posix()
        for p in sorted(ANDROID.rglob("*.kt"))
        if "fun canDialDriver(" in p.read_text(encoding="utf-8")
    ]
    c.ok(f"全源码树里 `fun canDialDriver(` **只有一处定义**（共 {len(defs)} 个文件）",
         defs == ["android/app/src/main/java/com/tapmoay/sorders/ui/common/DriverCall.kt"],
         f"实际在：{defs}")
    c.ok("判据文件不是空壳（读得到内容）", len(gate_src) > 120, f"只有 {len(gate_src)} 个字符")
    c.present("派单员放行", gate_src, r"role == Role\.DISPATCHER")
    # ⛔ 这条是本轮那一档的**唯一**代码判据：放宽成"所有货主"（去掉 `&& memberShipper`）当场红。
    c.present("**批发商放行**（判据本体里必须写 `role == Role.SHIPPER && memberShipper`）",
              gate_src, r"role == Role\.SHIPPER && memberShipper")
    # ⛔ 反向判据：把司机也算进来，当场红。
    c.absent("⛔ **司机不在**判据里（他不需要打给自己）", gate_src, r"Role\.DRIVER")

    print("\n== 3. 详情页怎么知道「我是不是批发商」 ==")
    # ⚠️ 判据在 `DetailBody` 里，而 `is_member` 只有 VM 取得到 → 必须**真的传下去**
    #    （漏了那一行：`memberShipper` 恒为 false，批发商那颗按钮永远不出现，而界面不报任何错）。
    c.present("页面把「我是不是批发商」传进 `DetailBody`", code, re.escape(MEMBER_WIRE))
    c.present("`DetailBody` 真的有这个参数（不然上面那一行编译不过）",
              code, r"memberShipper: Boolean = false,")
    vm = read_code(DETAIL_VM)
    c.present("详情 VM 提供 `isMemberShipper`（会话里没有 `is_member`，只能取一次 `/users/me`）",
              vm, r"var isMemberShipper by mutableStateOf\(false\)")
    c.present("取的是 `me().isMember`", vm, r"container\.repo\.me\(\)\.isMember")
    # ⚠️ 取不到时必须是 **false**（＝不给）：动作拿不准就别递出去。
    c.present("取不到时默认**不给**（`getOrDefault(false)`）",
              vm, r"runCatching \{ container\.repo\.me\(\)\.isMember \}\.getOrDefault\(false\)")
    c.absent("⛔ 不许默认给（`getOrDefault(true)` / `?: true`）", vm, r"isMember[\s\S]{0,40}\?: true")

    print("\n== 4. 判据有单测钉着（普通货主与司机那两条最容易被顺手放开）==")
    c.ok("有单测文件", DRIVER_CALL_TEST.exists(), f"缺 {DRIVER_CALL_TEST.name}")
    if DRIVER_CALL_TEST.exists():
        t = read(DRIVER_CALL_TEST)
        c.present("单测盯着「普通货主不给」", t,
                  r"assertFalse\(canDialDriver\(Role\.SHIPPER, memberShipper = false\)\)")
        c.present("单测盯着「司机不给」", t, r"assertFalse\(canDialDriver\(Role\.DRIVER")
        c.present("单测盯着「派单员 + 批发商能给」", t,
                  r"assertTrue\(canDialDriver\(Role\.SHIPPER, memberShipper = true\)\)")

    print("\n== 5. `DriverRow` 本身长什么样 ==")
    j = code.find("private fun DriverRow(")
    #: 取到**下一个函数定义**为止 = 这一颗组件自己的函数体（别把下一页的代码卷进来）。
    k = code.find("private fun ", j + 10)
    fn = code[j:k if k > j else j + 2000] if j >= 0 else ""
    c.present("它是一颗真按钮（`FilledTonalButton`），不是裸 `IconButton`",
              fn, r"FilledTonalButton\(")
    c.present("按钮上写着「拨号」", fn, r'Text\("拨号"\)')
    c.present("按钮带图标（用户定过：图标不能去掉）", fn, r"Icon\(\s*Icons\.Default\.Call")
    c.present("司机那一行有语义色（`MgrGreen` = 司机管理的颜色）", fn, r"tint = Color\(MgrGreen\)")
    c.present("号码不可拨（`onDial == null`）时整颗按钮不画", fn, r"if \(onDial != null\) \{")
    # ⚠️ 这条判据要**双向**：只断言"信息用了 weight"的话，把按钮挪到下一行照样绿。
    #    所以既要有 `Row { 信息 weight(1f); 按钮 }` 的顺序，也要**整个组件里只有这一个行容器**
    #    （按钮另起一行就必然多一个 `Row(` 或 `Row {` —— 两种写法都算，只认带括号的那种会漏）。
    n_row = len(re.findall(r"(?<![\w.])Row\s*[({]", fn))
    c.present("信息吃剩余宽度（`Column(Modifier.weight(1f))`）", fn, r"Column\(Modifier\.weight\(1f\)\)")
    c.ok("按钮与信息**同排**（组件里只有 1 个行容器，按钮没另起一行 —— 设计规范 §4.16.7）",
         n_row == 1, f"找到 {n_row} 个 `Row`/`Row(`")
    c.present("电话规则真的来自共用那一份（`core/InputRules.kt`）",
              code, r"import com\.tapmoay\.sorders\.core\.InputRules")
    c.ok("`core/InputRules.kt` 还在（上面那条 import 指得到东西）", INPUT_RULES.exists())

    print("\n== 6. 后端：下发的司机号码必须是**能拨的** ==")
    c.present("`driver_phone` 过 `strip_del_suffix`（软删后缀去尾）",
              orsp, r'data\["driver_phone"\] = strip_del_suffix\(du\.phone\)')
    c.absent("没有再把库里的原样值直接下发（`= du.phone`）",
             orsp, r'data\["driver_phone"\] = du\.phone\b')
    c.present("去尾用的是共用实现（`services/soft_delete.py`）",
              orsp, r"from app\.services\.soft_delete import strip_del_suffix")

    print("\n== 7. 配套：用例 / 规范 / 定位表（改了却没跟上 = 下一轮没人知道）==")
    c.ok("后端有用例钉住这条出参", BACKEND_TEST.exists(), f"缺 {BACKEND_TEST.name}")
    if BACKEND_TEST.exists():
        t = read(BACKEND_TEST)
        c.present("用例真的在验软删后缀被去干净（不是空跑）", t,
                  r'raw\.phone\)\.endswith\(f"_del\{did\}"\)[\s\S]{0,600}?after\["driver_phone"\] == "13900009999"')
    design = read(DESIGN)
    # ⚠️ 两个**不同**的字面量才算"挨着"：写成 `(拨号|脚本名)…(脚本名|拨号)` 是自欺 ——
    #    文档里「拨号」出现两次就自己配对了，删掉脚本名照样绿（反向验证当场抓到的 MISS）。
    c.present("设计规范里写了这条偏好（「拨号」按钮 + `canDialDriver` 挨着写）",
              design, r"拨号[\s\S]{0,600}?canDialDriver")
    c.present("并且写清了「普通货主与司机不给」（放宽的边界在文档里）",
              design, r"普通货主与司机不给")
    c.present("并且**指路到本判据**（否则下一轮没人找得到这条规矩）",
              design, r"_tools/qa/_check_order_driver_call\.py")
    loc = read(LOCATOR)
    rows = [ln for ln in loc.splitlines() if ln.startswith("| **订单详情页**")]
    c.ok("定位表的「订单详情页」那一行写了司机拨号这条（含判据脚本名）",
         len(rows) == 1 and "拨号" in rows[0] and "_check_order_driver_call.py" in rows[0],
         f"命中 {len(rows)} 行")
    # ⚠️ 锚的是**结论那一句**（不是"行里出现过『批发商』"）：这一行本来就引用了用户的整段原话
    #    （原话里就有"批发商"），只查关键词的话，把结论退回「只有派单端能拨」照样绿
    #    —— 反向验证当场抓到的 MISS。
    c.present("定位表那一行写的是新口径「只有派单员与批发商能拨」（退回旧口径就红）",
              rows[0] if rows else "", r"司机那一行：只有派单员与批发商能拨")
    _ = raw  # 原始文本（含注释）在本脚本里只用于"文件读得到"这一件事

    print("\n" + "=" * 60)
    total = c.passes + len(c.fails)
    if total < 28:
        print(f"❌ 只跑了 {total} 条判据（< 28）—— 判据在空转，停。")
        return 1
    if c.fails:
        print(f"❌ {len(c.fails)} 项不达标：")
        for f in c.fails:
            print("   - " + f)
        return 1
    print(f"✅ 全部 {c.passes} 项通过：司机电话只有派单员与批发商能拨，且拨出去的号是能拨的。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
