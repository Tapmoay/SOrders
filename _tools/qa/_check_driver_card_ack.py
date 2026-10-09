"""司机**在订单卡片上直接接单**（CHG-0081）：这一颗按钮的 8 条不许被静默破坏的规矩。

## 用户要的是什么（2026-10-08，台账 L-51）
原话：「这个确认订单，他的按钮是进入订单详情面才能确认，这个就太麻烦了…**直接在订单卡片里面的
最底下**…有一个按钮，他可以直接在那里点击确认…他就不需要直接的点进去…进行确认就可以了」。
→ 接单此前**只有**详情页那一个入口（`ui/order/OrderDetailScreen.kt` 那颗整宽 56dp 绿键），
现在卡片最底下也有一颗（`OrderCard` 的新槽 `bottomAction`，整宽、语义绿、与详情页同文案同高）。

## 为什么这条必须有机器的判据（这里每一处坏了都不报错、不崩、测试也不会红）
1. **接完单「来单了」还在喊**：`OrderDetailViewModel.ack()` 里那句 `container.newOrderPlayer.stop()`
   不是装饰 —— 有它才"接完就闭嘴"。列表上再多一条接单路径，漏掉它 = 司机接了单，
   语音还在喊「你有新的订单」（2026-09-16 定案里点名的反面）。
2. **一张单接单失败，屏幕上所有卡都冒同一句红字**：`ackError` 是个**单值**，
   而列表上每张卡都读它。判据必须钉住"按单号过滤"（`ackErrorOrderId`）。
3. **连点两下 = 后端 400**：`backend/app/services/order_flow.py::accept_order` 是条件 UPDATE，
   第二次必然撞空 → `400 这张单刚刚被改过（可能已被撤销/撤回/别人接过），请刷新后看看当前状态`。
   那条错**看起来像系统坏了**，而它其实只是"手滑点了两下" → 界面必须在请求在飞时置灰。
4. **状态门抄成硬编码 `"DISPATCHED"`**：与详情页那颗按钮的判据 `OrderStatusModel.ACKABLE`
   分叉 → 哪天 ACKABLE 多了/改了，两个入口给出**不同的**可点性（一边能接一边不能）。
5. **错误落点写错**：接单失败若写进页面级 `vm.error`，渲染门 `vm.error != null -> ErrorView(...)`
   会把**整个列表**顶掉 —— 司机连那张单都看不见了（设计规范 §4.8「错误的落点」）。
6. **判据只写在界面上**：`vm.ack()` 自己没有"已有请求在飞就别再发"的守卫的话，
   按钮那边改一行 `enabled` 就能把并发接单放进来。

## R4-BOUNDARY-JUSTIFICATION: 为什么代码边界解决不了这件事
"接单"这个动作**编译器认得**（`repo.driverAck(id)` 有类型），但上面 6 条**没有一条是类型属性**：
· `newOrderPlayer.stop()` 删掉，类型照样合法 —— 缺的那一层是"播报器是个全局单例"这件事的**副作用**；
· `ackError` 该按单号过滤，是"列表里有 N 张卡、而错误只有一个"的**数据形状**问题，
  `String?` 与 `Long?` 都合法；
· "请求在飞时置灰"是**时间**属性（同 §`_check_driver_tab_highlight` 那条：任何类型都表达不出
  "这两句必须相邻/这一刻必须禁用"）；
· 状态门该取哪个集合，是**跨文件的一致性**（详情页 ↔ 列表页 ↔ 后端状态机）。
所以判据只能落在源码结构上，且必须配反向验证 `_reverse_verify_driver_card_ack.py`
（20 条注入：把每一条规矩分别弄坏，看它真的变红）。
静默空转保护：`MIN_KT = 100`（目录被搬走 / 一个 .kt 都没扫到就红，不许"扫了 0 个也全绿"）。

## 判据
1. `OrderCard` 有 `bottomAction` 槽（`ColumnScope`），默认参数是**空**的，且卡片里**真的调用**它；
2. 司机任务页那次 `OrderCard(...)` 传了 `bottomAction`，条件里带 `vm.ordersTab == 0`
   （用"画的是哪一栏"而不是"想看哪一栏"，见 `_check_driver_tab_highlight.py`）；
3. 全仓**只有这一处**画「确认接单」；详情页那颗一个字没动（文案/色/高/图标/门）；
4. VM：`ack()`、三种收场（换那一条 / 失败拉真相 / 转圈收尾）、`newOrderPlayer.stop()`、
   并发守卫、`replacing by id`、状态门取自 `ACKABLE`；
5. 失败的那句话**落在卡片上**且按单号过滤（不许进页面级 error、不许每张卡都冒同一句）；
6. 按钮真的能按（`fillMaxWidth` + 56dp + 语义绿 + 白字），且两个状态声明在 `init` **之前**；
7. 后端 `accept_order` 的 CAS 那几行一个字没动（它正是"手滑点两下"的防线）；
8. `Color.White` 之类的 import 补齐了（编译不过等于没写）。

用法：python _tools/qa/_check_driver_card_ack.py
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
CARD = AND / "ui/common/OrderCard.kt"
SCREEN = AND / "ui/driver/DriverOrdersScreen.kt"
VM = AND / "ui/driver/DriverOrdersViewModel.kt"
DETAIL = AND / "ui/order/OrderDetailScreen.kt"
STATUS_MODEL = AND / "core/OrderStatusModel.kt"
BACKEND_FLOW = ROOT / "backend/app/services/order_flow.py"

#: 全仓至少要有这么多 .kt（防"目录被搬走 → 一个都没扫到 → 全绿"）。
MIN_KT = 100

#: 详情页那颗「确认接单」的**逐字**原文（2026-10-08 核实过；改它就是改另一个入口的行为）。
DETAIL_BUTTON = 'Text("确认接单", style = MaterialTheme.typography.titleSmall)'


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
        m = re.search(pattern, text, re.M)
        self.ok(label, m is not None, f"没找到 {pattern!r}")

    def absent(self, label: str, text: str, pattern: str) -> None:
        m = re.search(pattern, text, re.M)
        self.ok(label, m is None, f"命中：{m.group(0)!r}" if m else "")


def code_only(t: str) -> str:
    """去掉块注释与行注释（保留换行数，好让行号还对得上）。

    为什么要这样：这一轮反复用到的"原话/判据/为什么"全在注释里，其中就有
    `Text("确认接单"…)` 这类**看起来像代码**的引用 —— 判据抓的是**代码里**还有人画那颗按钮。
    """
    t = re.sub(r"/\*[\s\S]*?\*/", lambda m: chr(10) * m.group(0).count(chr(10)), t)
    return re.sub(r"//[^\n]*", "", t)


def read(p: Path) -> str:
    if not p.exists():
        raise SystemExit(f"找不到文件：{p}（被改名/搬走了？这条判据要跟着改）")
    return p.read_text(encoding="utf-8").replace("\r\n", "\n")


def main() -> int:
    c = Checker()
    card = read(CARD)
    screen = read(SCREEN)
    vm = read(VM)
    detail = read(DETAIL)
    status_model = read(STATUS_MODEL)
    flow = read(BACKEND_FLOW)

    print("== 1. OrderCard：第三个槽（卡片最底下那一整行） ==")
    c.present("签名里有 bottomAction（ColumnScope）",
              card, r"bottomAction: @Composable ColumnScope\.\(\) -> Unit = \{\}")
    c.present("默认空 → 其它列表逐像素不变（KDoc 写了这条理由）",
              card, r"默认空 = \*\*不画这一行\*\*")
    # ⚠️ 上面那条抓的是**注释里的理由**，注释在不在与代码对不对是两件事：这里再钉**代码本身**。
    #    默认值一旦写成非空（比如别的列表也被塞了一颗按钮），上面那条照样绿 —— 这条会红。
    c.ok("签名里那个默认值**确实**是空的（只认代码，不认注释）",
         re.search(r"bottomAction: @Composable ColumnScope\.\(\) -> Unit = \{\},?\s*\n", code_only(card)) is not None,
         "签名里的默认值不是 `= {}`")
    # ⚠️ 只看**函数体内**那一句调用：先把签名那段参数声明剪掉，否则会匹配到签名自己。
    body = card.split(") {\n", 1)[1] if ") {\n" in card else card
    c.present("卡片里真的调用了它（只加参数不调用 = 加了跟没加一样）",
              body, r"^\s{12}bottomAction\(\)\s*$")
    i_row = card.find("leading()\n                Spacer(Modifier.weight(1f))\n                extra()")
    # ⚠️ 必须**前后带换行**再数，而且用 `rfind`：
    #   · 不带换行 → 会先命中**签名里**那句参数声明（实测在 15255 之前），「位置」那条会假绿；
    #   · 只用 `rfind` → 往正文**再插一句**时它命中的仍是原来那一句，那条也会假绿（实测过）。
    #   所以这一条同时钉：**恰好一处** + 它排在动作行之后。删掉 / 重复插入 / 整句搬走，三种都红。
    call_needle = "\n            bottomAction()\n"
    c.ok("Card 里**恰好一处**调用它，且排在底部动作行**之后**（插一句、搬一句、删一句都要红）",
         card.count(call_needle) == 1 and card.rfind(call_needle) > i_row > 0,
         f"动作行@{i_row} / 调用@{card.rfind(call_needle)} / 共 {card.count(call_needle)} 处")

    print("\n== 2. 司机任务页：那一颗按钮接在哪、什么时候画 ==")
    c.present("那次 OrderCard(...) 传了 bottomAction",
              screen, r"bottomAction = \{")
    c.present("条件带『进行中那一栏』（用 ordersTab，不是 tab）",
              screen, r"if \(vm\.ordersTab == 0 && order\.status in OrderStatusModel\.ACKABLE")
    c.present("状态门取自 OrderStatusModel.ACKABLE（与详情页同一把尺）",
              screen, r"order\.status in OrderStatusModel\.ACKABLE")
    # 2026-10-08 真机取证后改的这一条：初版在门上多加了 `!order.isNewForDriver`，
    # 而那个字段的语义正是「已派单且这个司机还没接过」→ 与 ACKABLE（DISPATCHED）互斥，
    # 结果是**真需要接的新单一颗按钮都没有**（真机两张带「新任务」标的单当场证实）。
    # ⚠️ 必须查 `code_only(screen)`：这句在注释里也出现（就是下面那条"理由"），
    #    拿原文本查会把「注释里提到它」误判成「代码里还挂着它」。
    c.absent("门上**没有** `!order.isNewForDriver`（加了它＝新单永远没有按钮）",
             code_only(screen), r"!order\.isNewForDriver")
    c.present("那条『别再加它』的理由留在注释里（下一个人不会再犯）",
              screen, r"不要再加 `!order\.isNewForDriver`")
    c.present("点它调 vm.ack(order)",
              screen, r"onClick = \{ vm\.ack\(order\) \}")
    c.present("留了指路注释（原话 + 三个判据各有出处）",
              screen, r"直接在订单卡片里面的最底下")
    # 判据 3：全仓只有这一处画「确认接单」
    kts = sorted(AND.rglob("*.kt"))
    c.ok(f"扫到 {len(kts)} 个 .kt（≥{MIN_KT}，防目录被搬走时空转）",
         len(kts) >= MIN_KT, f"实际 {len(kts)}")
    sites = []
    for p in kts:
        t = code_only(read(p))
        if 'Text("确认接单"' in t:
            sites.append(p.relative_to(AND).as_posix())
    c.ok("『确认接单』的按钮**只有两处**（详情页 + 司机任务页），没有第三处悄悄冒出来",
         sorted(sites) == ["ui/driver/DriverOrdersScreen.kt", "ui/order/OrderDetailScreen.kt"],
         f"实际：{sites}")

    print("\n== 3. 详情页那颗一个字没动（同一动作不该在两个页面上长得不一样） ==")
    c.present("文案 + 字级逐字一致", detail, re.escape(DETAIL_BUTTON))
    c.present("整宽 56dp 主行动",
              detail, r"modifier = Modifier\.fillMaxWidth\(\)\.height\(56\.dp\)")
    # ⚠️ 详情页那边写的是**全限定名**（那个文件没有 import Color）：两处写法都要认，
    #    否则判据会因为「同一个颜色的两种合法写法」误报。
    c.present("语义绿 0xFF49A67A（详情页那颗；全限定名与 import 两种写法都认）",
              detail, r"containerColor = (?:androidx\.compose\.ui\.graphics\.)?Color\(0xFF49A67A\)")
    c.present("状态门还是 ACKABLE",
              detail, r"order\.status in OrderStatusModel\.ACKABLE")
    c.present("图标还是 CheckCircle",
              detail, r"Icons\.Default\.CheckCircle")

    print("\n== 4. VM：这一个动作的三种收场 ==")
    c.present("有 ack(order: OrderDto)", vm, r"fun ack\(order: OrderDto\) \{")
    c.present("并发守卫：已有请求在飞就直接不管",
              vm, r"if \(ackingOrderId != null\) return")
    c.present("成功后**按 id** 换掉那一条（不是按下标）",
              vm, r"orders = orders\.map \{ if \(it\.id == updated\.id\) updated else it \}")
    c.present("接单成功 → 停掉「来单了」播报（2026-09-16 定案的反面就在这里）",
              vm, r"container\.newOrderPlayer\.stop\(\)")
    c.present("成功后也告诉别的页面状态变了",
              vm, r"container\.realtimeHub\.notifyOrdersChanged\(\)")
    c.present("失败 → 记下那句话 + 是**哪一张单**的",
              vm, r"ackError = toApiException\(e\)\.message\s*\n\s*ackErrorOrderId = order\.id")
    c.present("失败还要把列表拉回真相（那句错说的是：你已经不是这样了）",
              vm, r"ackErrorOrderId = order\.id[\s\S]{0,400}?\n\s+load\(\)")
    c.present("转圈收尾：finally 里放下 ackingOrderId",
              vm, r"\} finally \{\s*\n\s*ackingOrderId = null\s*\n\s*\}")
    c.present("状态门不硬编码 DISPATCHED（注释里提到不算，看代码）",
              vm, r"ACKABLE")

    print("\n== 5. 失败的那句话落在卡片上（设计规范 §4.8「错误的落点」） ==")
    c.present("VM 里有 ackErrorOrderId（否则一张单失败、所有卡都冒红字）",
              vm, r"var ackErrorOrderId by mutableStateOf<Long\?>\(null\)\s*\n\s*private set")
    c.present("Screen 按单号过滤再画那句话",
              screen, r"FormErrorLine\(\s*\n\s*if \(vm\.ackErrorOrderId == order\.id\) vm\.ackError else null,")
    # ⛔ 接单的错**不许**写进页面级 error：渲染门会拿它顶掉整个列表。
    m = re.search(r"var error by mutableStateOf<String\?>\(null\)", vm)
    c.ok("页面级 error 还在（这一页「没加载出来」仍然要说）", m is not None)
    i_ack = vm.find("fun ack(order: OrderDto)")
    i_next = vm.find("\n    fun ", i_ack + 1)
    ack_body = vm[i_ack:i_next] if i_next > 0 else vm[i_ack:]
    c.absent("ack() 体内没有任何一句写页面级 error（写了就把列表顶掉）",
             ack_body, r"(?<!ack)error = ")

    print("\n== 6. 按钮真的能按，状态声明位置对 ==")
    c.present("整宽 + 56dp（与详情页那颗同高）",
              screen, r"modifier = Modifier\.fillMaxWidth\(\)\.padding\(top = 10\.dp\)\.height\(56\.dp\)")
    c.present("语义绿底 + 白字",
              screen, r"containerColor = Color\(0xFF49A67A\),\s*\n\s*contentColor = Color\.White")
    c.present("请求在飞时置灰（连点两下 = 后端 400）",
              screen, r"enabled = !locked")
    c.present("在飞的那一张画转圈",
              screen, r"val busy = vm\.ackingOrderId == order\.id")
    c.present("转圈是白的（绿底上的默认色几乎看不见）",
              screen, r"CircularProgressIndicator\(\s*\n\s*modifier = Modifier\.size\(20\.dp\),\s*\n\s*color = Color\.White")
    c.present("import 了 Color（没 import 编译就红，写在这里省得下次又忘）",
              screen, r"^import androidx\.compose\.ui\.graphics\.Color$")
    c.present("import 了 CheckCircle",
              screen, r"^import androidx\.compose\.material\.icons\.filled\.CheckCircle$")
    for name in ("ackingOrderId", "ackError", "ackErrorOrderId"):
        i_state = vm.find(f"var {name} by mutableStateOf")
        # ⚠️ 必须找**类里那一个** `    init {`（4 空格缩进）。直接 find("init {") 会先命中
        #    `private val FINISHED_STATUSES` 上方 KDoc 里的字样（实测偏移 3126），
        #    那样「状态在 init 之前」这条会**假红**——不是代码错，是判据找错了地方。
        i_init = vm.find("\n    init {")
        c.ok(f"{name} 声明在 init **之前**（属性初始化按书写顺序执行；写在后面打开这一页就崩）",
             i_state >= 0 and i_init >= 0 and i_state < i_init,
             f"{name}@{i_state} / init@{i_init}")

    print("\n== 7. 后端那个 CAS 一个字没动（它正是「手滑点两下」的防线） ==")
    c.present("accept_order 仍在 services/order_flow.py",
              flow, r"def accept_order\(db: Session, order: Order, driver: User\) -> None:")
    c.present("只认 DISPATCHED → ACCEPTED",
              flow, r"if order\.status != OrderStatus\.DISPATCHED:\s*\n\s*raise ValueError\(\"仅「已派单」订单可确认接单\"\)")
    c.present("条件 UPDATE 带 driver_id == 我",
              flow, r"Order\.driver_id == driver\.id,   # 只有被派的那个人能接（端点的取单已挡，这里再钉一次）")
    c.present("CAS 撞空 → 回滚 + 那句中文错",
              flow, r"if claimed\.rowcount != 1:\s*\n\s*db\.rollback\(\)\s*\n\s*raise ValueError\(")
    c.present("ackableView 的状态清单里有它（状态模型与后端同一把尺）",
              status_model, r'val ACKABLE: Set<String> = setOf\("DISPATCHED"\)')

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
