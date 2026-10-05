"""司机任务页的「这一笔画的是哪一栏」必须来自**屏幕上那批数据**，不是来自用户想看的 tab（BUG-0014）。

## 用户报的现象（2026-10-06，台账 L-01）
「切「已完成」时卡片件数**先由红变紫、字号由 titleLarge 变 titleMedium**，一个往返后才换成该栏数据」。

## 机制
`ui/driver/DriverOrdersScreen.kt` 的卡片高亮原来是 `highlight = vm.tab == 0`：
`tab` 在点下去的那一瞬间就变了，而 `vm.orders` 要等网络回来才整体替换 ——
于是切换的那一个往返里，**属于「进行中」的那批单**被画成已完成的样式。

## 为什么这条必须有机器的判据
这个毛病**不报错、不崩、测试也不会红**：画错的只是颜色与字号，数据本身是对的；
而"改回去"只需要有人顺手写一句 `highlight = vm.tab == 0`（看上去更直观）。
所以判据要钉在**源码结构**上：谁是"画的是哪一栏"的唯一来源、以及两个状态是不是原子地一起换。

## R4-BOUNDARY-JUSTIFICATION: 为什么代码边界解决不了这件事
「这一笔画的是哪一栏」不是类型属性：`highlight` 是个 `Boolean`，`ordersTab` 与 `tab` 都是 `Int`，
编译器眼里 `highlight = vm.tab == 0` 完全合法 —— 它甚至更"直观"（用户就是点了那个 tab）。
缺的那一层是**时间**：`tab` 在手指落下那一瞬就变，`orders` 要等一个网络往返才整体替换，
**这中间那一帧该画什么**，语言、类型系统与 Lint 都说不出来（没有任何类型能表达"这两句必须相邻"）。
所以判据只能落在源码结构上：谁是"画的是哪一栏"的唯一来源、两句赋值是否相邻、渲染门排在哪一位。
反向破坏用例见 `_reverse_verify_driver_tab_highlight.py`（13 条改坏 + 1 条新建"按 vm.tab 算高亮"的越权页 + 还原后逐字节比对）。
静默空转保护：`MIN_KT = 100`（目录被搬走 / 一个 .kt 都没扫到就红，不许"扫了 0 个也全绿"）。

## 判据（每条都能被反向验证弄红，见 `_reverse_verify_driver_tab_highlight.py`）
1. VM 有 `ordersTab`（private set），且声明在 `init` **之前**（属性初始化按书写顺序执行）；
2. `load()` 在**挂起点之前**捕获 `val wanted = tab`；
3. 取数用的是 `wanted` 而不是 `tab`；
4. `orders = fetched` 与 `ordersTab = wanted` **相邻**（中间没有挂起点）；
5. 渲染门有 `vm.ordersTab != vm.tab -> LoadingBox()`，且排在 `error` **之后**（否则失败被顶掉）；
6. `highlight` 取自 `vm.ordersTab`，**全仓不许再有** `highlight = vm.tab`
   （扫的是**代码**：先去掉块注释与行注释再比 —— 注释里点名那句正是为了说清"从前错在哪"）；
7. 卡片上 highlight 的**呈现**没被顺手改掉（红+大号 / 紫+中号）；
8. 两处都留了"别改回去"的指路注释。

用法：python _tools/qa/_check_driver_tab_highlight.py
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
VM = AND / "ui/driver/DriverOrdersViewModel.kt"
SCREEN = AND / "ui/driver/DriverOrdersScreen.kt"
CARD = AND / "ui/common/OrderCard.kt"

#: 全仓至少要有这么多 .kt（防"目录被搬走 → 一个都没扫到 → 全绿"）。
MIN_KT = 100


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


def code_only(t: str) -> str:
    """去掉块注释与行注释（保留换行数，好让行号还对得上）。

    为什么要这样：`highlight = vm.tab == 0` 这句在 VM 的 KDoc 里**必须留着** ——
    它写的正是"从前错在哪"。判据要抓的是**代码里**还有人按用户想看的 tab 算高亮。
    """
    t = re.sub(r"/\*[\s\S]*?\*/", lambda m: chr(10) * m.group(0).count(chr(10)), t)
    return re.sub(r"//[^\n]*", "", t)


def read(p: Path) -> str:
    if not p.exists():
        raise SystemExit(f"找不到文件：{p}（被改名/搬走了？这条判据要跟着改）")
    return p.read_text(encoding="utf-8").replace("\r\n", "\n")


def main() -> int:
    c = Checker()
    vm = read(VM)
    screen = read(SCREEN)
    card = read(CARD)

    print("== 1. VM：多一个『屏幕上这批单属于哪一栏』的状态 ==")
    c.present("有 ordersTab（private set）",
              vm, r"var ordersTab by mutableStateOf\(0\)\s*\n\s*private set")
    i_state = vm.find("var ordersTab by mutableStateOf(0)")
    i_init = vm.find("init {")
    c.ok("ordersTab 声明在 init **之前**（属性初始化按书写顺序执行；写在后面会崩）",
         i_state >= 0 and i_init >= 0 and i_state < i_init,
         f"ordersTab@{i_state} / init@{i_init}")
    c.present("注释里说清它与 tab 是两件事（想看哪一栏 vs 画的是哪一栏）",
              vm, r"用户\*\*想看\*\*哪一栏")

    print("\n== 2. VM：取数这一趟是给哪一栏取的，在挂起点之前钉死 ==")
    c.present("load() 里在 launch **之前**捕获 val wanted = tab",
              vm,
              r"fun load\(\) \{[\s\S]{0,400}?val wanted = tab\s*\n\s*loadJob = viewModelScope\.launch \{")
    c.present("状态清单取自 wanted（不是 tab）", vm, r"val statuses = if \(wanted == 0\)")
    c.present("日期参数也取自 wanted", vm, r"dateFrom = if \(wanted == 1\) dateFrom else null")
    c.present("orders = fetched 与 ordersTab = wanted **相邻**（中间没有挂起点）",
              vm, r"orders = fetched\s*\n\s*ordersTab = wanted")
    c.present("注释里点了『必须相邻』的理由（否则下一轮会有人拆开）",
              vm, r"这两句\*\*必须相邻\*\*")

    print("\n== 3. Screen：高亮与渲染门都看『画的是哪一栏』 ==")
    c.present("卡片高亮取自 vm.ordersTab", screen, r"highlight = vm\.ordersTab == 0\)")
    c.present("渲染门有『不是这一栏 → LoadingBox』那一档",
              screen, r"vm\.ordersTab != vm\.tab -> LoadingBox\(\)")
    i_err = screen.find("vm.error != null -> ErrorView(")
    i_stale = screen.find("vm.ordersTab != vm.tab -> LoadingBox()")
    c.ok("新那一档排在 error **之后**（失败仍能看见，不被『数据不是这一栏』顶掉）",
         i_err >= 0 and i_stale >= 0 and i_err < i_stale,
         f"error@{i_err} / ordersTab@{i_stale}")
    c.present("Screen 也留了『别改回去』的指路", screen, r"BUG-0014")

    print("\n== 4. 全仓不许再有 highlight = vm.tab（清单自己算）==")
    kts = sorted(AND.rglob("*.kt"))
    c.ok(f"扫到 {len(kts)} 个 .kt（≥{MIN_KT}，防目录被搬走时空转）", len(kts) >= MIN_KT, f"实际 {len(kts)}")
    bad = []
    for p in kts:
        t = code_only(read(p))
        for m in re.finditer(r"highlight\s*=\s*vm\.tab\b", t):
            bad.append(f"{p.relative_to(AND).as_posix()}:{t[:m.start()].count(chr(10)) + 1}")
    c.ok("没有任何一处按 vm.tab 算高亮（只看代码，不看注释）", not bad, "；".join(bad))

    print("\n== 5. 卡片上 highlight 的呈现没被顺手改掉 ==")
    c.present("highlight=true → 大号",
              card, r"if \(highlight\) MaterialTheme\.typography\.titleLarge else MaterialTheme\.typography\.titleMedium")
    c.present("highlight=true → 红；false → 紫",
              card, r"if \(highlight\) Color\(DangerRed\) else Color\(ProductPurple\)")
    c.present("件数/时间那一行还在（没把整行删空）",
              card, r"sharedUnitOf\(order\.orderProducts\.map \{ it\.unit \}\)")

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
