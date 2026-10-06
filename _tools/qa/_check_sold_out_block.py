# -*- coding: utf-8 -*-
"""红线：沽清（下架）的商品**真的不能卖** —— 界面点不动、提交拦得住、服务端也拒（台账 L-35 / BUG-0017）。

## 这条是怎么来的
2026-10-07 用户台账 L-35：商品沽清（`products.is_active = false`）之后**只贴了一张角标** ——
卡还亮着、圆形加号还能点、还能加进购物车、点「确定下单」**真的下得出去**（服务端只拒"不在库/已删除"）。
用户 m01347 的原话：「灰掉了之后**就不能点**……就是**整卡变灰**嘛……就是**拦住不让下**，
不可能是提示后他仍然可以下呀。」

而仓库自己早就把这件事写下来过：`ai/AiWriteMasterData.kt` 那条注释逐字写着
「App 的选品页是 `includeInactive=true` + 只画一个红色角标、**加号仍可点**」——
所以 L-35 不是一个新功能，是**把仓库自己承认的谎补上**。

## 为什么必须有机器的判据
"把卡变灰 + 加个 enabled=false"本身很容易做对，难的是它**四道都不被绕开**：

1. 加号那条线：`onClick = { onAdd() }`（照点不误）与 `onClick = { if (!soldOut) onAdd() }`
   类型上完全一样；只写 `enabled = false` 也不够 —— 灰按钮**照样收点击**（本仓库踩过）。
2. 提交那道闸：选品页点不动了，但**购物车里可能本来就有它**（先加、后被沽清）；
   这道闸写在 `submit` 里，改回内联一份、或者被挪到别的分支后面，界面上一点看不出来。
3. 服务端那道闸：客户端只挡界面，**AI 下单与老包绕得过**；`build_order_products` 里那句
   `if not prod.is_active:` 被删掉、或者被挪到 `if pid is not None` 之外（手输商品也被误伤），
   编译、单测、界面全绿。
4. **说法的第二份真相**：AI 写工具那条 blurb 与文件头的注释一起描述"下架之后会怎样"，
   改了行为不改说法，模型就会继续按旧说法回答用户（L-35 报的就是这一类谎）。

所以判据分五层（客户端选品页 / 提交前那道 / 服务端那条 / 别处不许变 / 说法与行为一致），
并且**自带空转闸**：扫到的界面文件数、被抽出来的函数体长度、以及**判据自己的总项数**都要达标 ——
少了任何一头，这条红线会安静地全绿，比没有判据更危险。

R4-BOUNDARY-JUSTIFICATION: 这一条**边界解决不了**。病是「沽清只贴了角标」，而
`onClick = { onAdd() }`（点得动）与 `onClick = { if (!soldOut) onAdd() }`（点不动）、
带与不带 `if not prod.is_active:` 的 `build_order_products`，**类型上完全一样**：
漏掉任何一处都照样编译、照样跑单测、界面上也看不出区别（除非有人在模拟器里真的点一下）。
AI 那条 blurb 更是纯文案，没有任何编译器会拦它。所以只能扫**结构**：三段代码里那句判断在不在、
放在哪一层分支里、别处有没有第二份内联实现、"说法"有没有跟着行为一起改。
配套：python _tools/qa/_reverse_verify_sold_out_block.py（12 种破坏方式全被抓）；
「屏幕上真的灰了、真的点不动」那一头由模拟器实测的截图负责（`shots/bug0017_*_5556.png`）。
本判据只读源码与文档（`read()`），不连库、不 import 后端、不跑迁移。

用法：python _tools/qa/_check_sold_out_block.py
     python _tools/qa/_check_sold_out_block.py --list   # 只列它到底在查什么
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
# 注释剥离**只有一份实现**（抄一份必踩同一个坑）
from _check_product_card_single_source import strip_comments  # noqa: E402
from _airepo import refuse_if_injecting  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"

PICKER = AND / "ui/common/ProductPicker.kt"
VM = AND / "ui/shipper/OrderCreateViewModel.kt"
KIT = AND / "ui/common/ProductCardKit.kt"
CHECKLIST = AND / "ui/common/ProductCheckList.kt"
AI_MD = AND / "ai/AiWriteMasterData.kt"
REPO = AND / "data/repo/AppRepository.kt"
APIS = AND / "data/remote/api/Apis.kt"
DETAIL_VM = AND / "ui/order/OrderDetailViewModel.kt"
POOL_VM = AND / "ui/dispatcher/DispatcherPoolViewModel.kt"
ORDER_FLOW = ROOT / "backend/app/services/order_flow.py"
ORDER_CMD = ROOT / "backend/app/commands/order.py"
TEST_PY = ROOT / "backend/tests/test_order_sold_out.py"
TEST_KT = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ui/shipper/ProductPickerTest.kt"
SPEC = ROOT / "docs/changes/BUG-0017.md"
README = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"
REVERSE = "_tools/qa/_reverse_verify_sold_out_block.py"

#: 扫到的界面文件数下限（防目录改名 / 搬走之后"一个文件都没扫到"也算过）
MIN_UI_FILES = 100

#: 抽出来的函数体字符数下限（**抽取失效比判据腐烂更危险** —— 那会变成一条永远绿的检查）
BODY_FLOOR = 300

#: 服务端那条闸所在函数的体量下限（`build_order_products` 比界面函数长得多）
SERVER_BODY_FLOOR = 800

#: ⛔ 空转即停：判据自己的总项数下限（少了就是判据被删空 —— 比如整段被注释掉）
MIN_ITEMS = 40

#: 客户端与服务端**同一句话**的两个关键片段（两边口径一起变，别各说各的）
SAME_WORDS = ["已经沽清（下架）", "不能再下单"]


def read(p: Path) -> str:
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def code(p: Path) -> str:
    return strip_comments(read(p))


def count(needle: str, text: str) -> int:
    return text.count(needle)


def fn_body(src: str, sig: str) -> str:
    """sig（如 `private fun ProductRow(`）那个函数的**函数体**（按大括号配对，不是按行猜）。"""
    i = src.find(sig)
    if i < 0:
        return ""
    b = src.find("{", i)
    if b < 0:
        return ""
    depth = 0
    for j in range(b, len(src)):
        ch = src[j]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return src[b : j + 1]
    return ""


def py_body(src: str, sig: str) -> str:
    """`.py` 里那个函数的**函数体**（按缩进，不按大括号 —— Kotlin 那套在这里抽不到东西）。

    ⚠️ 抽取失效比判据腐烂更危险：抽不到就只能"一个字符串都不在里面"，检查会安静地全绿。
    """
    lines = src.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.startswith(sig)), -1)
    if start < 0:
        return ""
    indent = len(lines[start]) - len(lines[start].lstrip())
    # 签名可能跨多行（def build_order_products( / db: Session, / lines: list[Any], / ) -> list:）
    # —— 那几行的中间行缩进 ≥ 定义缩进，只有**收尾那一行**的缩进会回到定义缩进且以冒号结尾。
    head = start
    for i in range(start, min(start + 20, len(lines))):
        ln = lines[i]
        if i > start and ln.rstrip().endswith(":") and (len(ln) - len(ln.lstrip())) <= indent:
            head = i
            break
    out = []
    for ln in lines[head + 1 :]:
        if not ln.strip():
            out.append(ln)
            continue
        cur = len(ln) - len(ln.lstrip())
        if cur <= indent:
            break
        out.append(ln)
    return "\n".join(out)


def indent_of(src: str, needle: str) -> int:
    """那一行**开头有多少个空格**（找不到 → -1）。"""
    i = src.find(needle)
    if i < 0:
        return -1
    return i - (src.rfind("\n", 0, i) + 1)


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

    @property
    def total(self) -> int:
        return self.passes + len(self.fails)

    def report(self, title: str) -> int:
        print()
        print(f"===== {title} =====")
        print(f"  通过 {self.passes} 项，失败 {len(self.fails)} 项，共 {self.total} 项")
        for f in self.fails:
            print(f"    - {f}")
        return 1 if self.fails else 0


def main() -> int:
    if refuse_if_injecting("沽清（下架）商品不许下单检查"):
        return 1

    c = Checker()
    print("沽清（下架）的商品真的不能卖（台账 L-35 / BUG-0017）：2026-10-07")

    # ---- 0. 空转闸：先证明"确实扫到了东西" ----
    ui_files = list(AND.rglob("*.kt"))
    c.ok(
        f"扫到的界面文件数 ≥ {MIN_UI_FILES}（防目录搬走 → 判据空转）",
        len(ui_files) >= MIN_UI_FILES,
        f"实际 {len(ui_files)}",
    )
    for p, why in (
        (PICKER, "选品页（整卡变灰、加号点不动）"),
        (VM, "提交前那道闸 + 顶层谓词 soldOutLine"),
        (ORDER_FLOW, "服务端 build_order_products（唯一那条下单路）"),
        (TEST_KT, "客户端纯逻辑单测"),
        (TEST_PY, "服务端单测"),
    ):
        c.ok(f"{p.relative_to(ROOT).as_posix()} 存在（{why}）", p.exists(), "文件被搬走 / 改名了")

    picker = code(PICKER)
    vm = code(VM)
    kit = code(KIT)
    checklist = code(CHECKLIST)
    ai = code(AI_MD)
    flow = code(ORDER_FLOW)

    row = fn_body(picker, "private fun ProductRow(")
    submit = fn_body(vm, "fun submit(")
    pred = fn_body(vm, "fun soldOutLine(")
    server = py_body(flow, "def build_order_products(")
    c.ok(f"ProductRow 函数体抽得出来（≥ {BODY_FLOOR} 字符）", len(row) >= BODY_FLOOR, f"只抽到 {len(row)} 字符 —— 判据会空转")
    c.ok("submit 函数体抽得出来", len(submit) >= BODY_FLOOR, f"只抽到 {len(submit)} 字符")
    c.ok("soldOutLine 函数体抽得出来", len(pred) >= 60, f"只抽到 {len(pred)} 字符")
    c.ok(
        f"build_order_products 函数体抽得出来（≥ {SERVER_BODY_FLOOR} 字符）",
        len(server) >= SERVER_BODY_FLOOR,
        f"只抽到 {len(server)} 字符",
    )

    # ---- 1. 客户端选品页：整卡变灰 + 加号点不动 ----
    soldout_def = "val soldOut = !product.isActive"
    c.ok(
        "选品页算出了这一格是不是沽清（val soldOut = !product.isActive，恰一处）",
        count(soldout_def, picker) == 1,
        f"{count(soldout_def, picker)} 处",
    )
    c.ok("那句话落在 ProductRow 里（选品页那一格）", soldout_def in row, "不在 ProductRow 里")
    c.ok(
        "整卡变灰：底色换成 surfaceVariant.copy(alpha = 0.45f)",
        "MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.45f)" in row,
        "底色没跟着 soldOut 走",
    )
    c.ok(
        "整卡变灰：内容一起暗（.alpha(if (soldOut) 0.6f else 1f) 落在 ProductLine 的 modifier 上）",
        "Modifier.padding(10.dp).alpha(if (soldOut) 0.6f else 1f)" in row,
        "内容那层没有 alpha",
    )
    c.ok(
        "导入的是 androidx.compose.ui.draw.alpha（少了这个 import 编译不过）",
        "import androidx.compose.ui.draw.alpha" in read(PICKER),
        "import 没了",
    )
    c.ok(
        "加号：onClick 里自己再拦一道（onClick = { if (!soldOut) onAdd() }）",
        "onClick = { if (!soldOut) onAdd() }" in row,
        "onClick 又变成照点不误了",
    )
    c.ok(
        "加号：enabled = !soldOut（灰掉 + 连涟漪都没有）",
        "enabled = !soldOut" in row,
        "enabled 没了（灰按钮照样收点击）",
    )
    c.ok(
        "加号：禁用态的两个颜色都给了（不然灰得看不出来）",
        "disabledContainerColor" in row and "disabledContentColor" in row,
        "禁用配色缺一个",
    )
    c.ok(
        "ProductRow 里 onAdd() 只出现一次（就是那道带闸门的调用，没有第二条入口）",
        count("onAdd()", row) == 1,
        f"{count('onAdd()', row)} 处 —— 多出来的那一处就是绕开闸门的入口",
    )
    c.ok(
        "⛔ 全库不许再有 onClick = { onAdd() } 这种照点不误的写法",
        count("onClick = { onAdd() }", "".join(code(p) for p in ui_files)) == 0,
        "又有人写了一条不带闸门的入口",
    )
    c.ok(
        "角标仍然是共用的那一个（badge = if (product.isActive) null else ProductSoldOutBadge()）",
        "ProductSoldOutBadge()" in row,
        "选品页自己画了一个角标",
    )
    c.ok(
        "⛔ 共用件 ProductLine 没有被改脏（ProductCardKit.kt 里不许出现 soldOut / isActive 判定）",
        "soldOut" not in kit,
        "有人把沽清判断塞进了共用件（管理页、批量页会一起变）",
    )

    # ---- 2. 提交前那道闸：购物车里混进沽清行也拦住 ----
    c.ok(
        "谓词是顶层纯函数（fun soldOutLine(lines: List<LineDraft>, products: List<ProductDto>)：单测能直接调）",
        "fun soldOutLine(lines: List<LineDraft>, products: List<ProductDto>): LineDraft?" in vm,
        "谓词被挪进 ViewModel 里了（单测就调不到）",
    )
    c.ok(
        "谓词认得沽清（ln.productId != null && …?.isActive == false）",
        "ln.productId != null" in pred and "?.isActive == false" in pred,
        "谓词不成立 —— 手输商品会被误伤，或者沽清行压根不认",
    )
    c.ok(
        "submit 里只调那一个函数（val soldOut = soldOutLine(lines, products)）",
        "val soldOut = soldOutLine(lines, products)" in submit,
        "submit 不再用那个谓词",
    )
    c.ok(
        "⛔ submit 里没有第二份内联实现（谓词只有 soldOutLine 那一份）",
        count("firstOrNull { ln ->", vm) == 1 and count("firstOrNull { ln ->", submit) == 0,
        f"全文件 {count('firstOrNull { ln ->', vm)} 处、submit 里 {count('firstOrNull { ln ->', submit)} 处",
    )
    c.ok(
        "拦住时指认的是哪一件、还说了怎么脱身（「」+ 已经沽清（下架），不能再下单，先删掉这一行再提交）",
        "「${soldOut.name}」已经沽清（下架），不能再下单，先删掉这一行再提交" in submit,
        "文案变了 / 没说清怎么办",
    )
    i_noprice = submit.find("noPrice != null ->")
    i_soldout = submit.find("soldOut != null ->")
    c.ok(
        "两道闸都在，且沽清那道排在「没有价格」之后（先报更早的那件事）",
        i_noprice >= 0 and i_soldout > i_noprice,
        f"noPrice 在第 {i_noprice} 字符、soldOut 在第 {i_soldout} 字符",
    )
    c.ok(
        "回归：原来那两道（空行 / 没价格）一个字没动",
        "lines.isEmpty() -> error =" in submit and "没有价格（这件商品已不在商品库）" in submit,
        "把原有的闸门顺手改掉了",
    )
    c.ok(
        "驳回的话是立刻说的（走 error 那条同步闸，不是等服务端 422 转一圈）",
        "error = " in submit and "soldOut != null ->" in submit,
        "没有写进 error",
    )
    c.ok(
        "客户端单测盯着这个谓词（ProductPickerTest 里调 soldOutLine，≥ 4 条）",
        count("soldOutLine(", code(TEST_KT)) >= 4,
        f"只调了 {count('soldOutLine(', code(TEST_KT))} 次",
    )

    # ---- 3. 服务端那道拒：AI 下单 / 老包绕得过界面，绕不过它 ----
    c.ok(
        "服务端在 build_order_products 里判了在售（if not prod.is_active:）",
        "if not prod.is_active:" in server,
        "服务端那道闸没了 —— 沽清商品立刻又能变成订单行",
    )
    c.ok(
        "判定之后立刻 raise ValueError（不是只记一条日志）",
        "raise ValueError(" in server[server.find("if not prod.is_active:") :][:400],
        "判了但没拒",
    )
    c.ok(
        "服务端那句话与客户端同口径（已经沽清（下架）＋ 不能再下单）",
        all(w in server for w in SAME_WORDS),
        f"缺：{[w for w in SAME_WORDS if w not in server]}",
    )
    c.ok(
        "服务端也让用户能脱身（说了删掉这一行 / 换一件）",
        "请先删掉这一行" in server,
        "只说不许，没说不许之后怎么办",
    )
    i_pid = server.find("if pid is not None:")
    i_none = server.find("if prod is None:")
    i_del = server.find("if prod.is_deleted:")
    i_act = server.find("if not prod.is_active:")
    # ⚠️ 只看"谁先谁后"不够：把沽清那道**退回上一层缩进**之后，四行仍然是"后出现的"，
    #    可手输的自定义商品（没有 product_id）也一起撞上它了 —— 用户没填商品编号，
    #    凭什么拿目录里那件商品的停用状态拒他。缩进必须真的在同一层。
    ind = [indent_of(server, n) for n in
           ("if pid is not None:", "if prod is None:", "if prod.is_deleted:", "if not prod.is_active:")]
    c.ok(
        "三道判定都在「商品库里有这件商品」那一层里（if pid is not None 之内）",
        i_pid >= 0 and i_none > i_pid and i_del > i_none and i_act > i_del
        and ind[1] == ind[2] == ind[3] > ind[0],
        f"pid={i_pid} / 不在库={i_none} / 已删除={i_del} / 已沽清={i_act}；缩进={ind}",
    )
    c.ok(
        "手输的自定义商品仍然不受影响（没有 product_id 的行走不到那一段）",
        i_pid >= 0 and "if not prod.is_active:" in server[i_pid:],
        "闸门挪到了 pid 判断之外",
    )
    c.ok(
        "成本快照仍然在闸门之后定格（沽清的行不会先落一个成本）",
        i_act >= 0 and server.find("cost_snap = prod.cost_price") > i_act,
        "顺序反了：先定格成本再判在售",
    )
    c.ok(
        "回归：原来那两句仍在（不在库里 / 已经删除了）",
        "已经不在商品库里" in server and "已经删除了" in server,
        "把原来的拒绝顺手改掉了",
    )
    c.ok(
        "⛔ 那句服务端文案全后端只有一份（别的模块不许再编一句自己的）",
        [p.relative_to(ROOT).as_posix() for p in (ROOT / "backend/app").rglob("*.py") if "已经沽清（下架）" in read(p)]
        == ["backend/app/services/order_flow.py"],
        "出现了第二份（AI 提示词 / 接口文档 / 别的服务里又写了一句）",
    )
    call_sites = [
        p.relative_to(ROOT).as_posix()
        for p in (ROOT / "backend").rglob("*.py")
        if "build_order_products(" in read(p) and "def build_order_products(" not in read(p)
    ]
    c.ok(
        "老单不走这条路：build_order_products 的调用点只有下单那一处（改数量 / 转单 / 拆单都不经过）",
        call_sites == ["backend/app/commands/order.py"],
        f"调用点：{call_sites}",
    )
    c.ok(
        "调用点确实在下单命令里（backend/app/commands/order.py 的 create_order）",
        "lines = build_order_products(db, body.lines)" in read(ORDER_CMD),
        "调用点换了地方 —— 得重新确认谁在用它",
    )
    c.ok(
        "服务端单测 ≥ 6 条（含「被拒时一件订单都没落库」）",
        count("def test_", code(TEST_PY)) >= 6 and "query(Order).count()" in code(TEST_PY),
        f"只数到 {count('def test_', code(TEST_PY))} 条",
    )

    # ---- 4. 别处不许变（这次改动的边界）----
    c.ok(
        "可见范围 / 授权页（ProductCheckList）下架商品**仍可勾**：勾选闸只看 locked",
        "clickable(enabled = !locked) { onToggleProduct(p.id) }" in checklist and "enabled = p.isActive" not in checklist,
        "有人把沽清当成了「不许授权」",
    )
    c.ok(
        "可见范围页仍然画着那枚共用角标（下架要看得见，只是不拦勾选）",
        "ProductSoldOutBadge()" in checklist,
        "角标被拿掉了",
    )
    c.ok(
        "角标文案全库只有一处（「已沽清」），且定义在 ProductCardKit.kt",
        count("已沽清", kit) == 1 and count("fun ProductSoldOutBadge(", "".join(code(p) for p in ui_files)) == 1,
        f"ProductCardKit 里 {count('已沽清', kit)} 处；全库定义 {count('fun ProductSoldOutBadge(', ''.join(code(p) for p in ui_files))} 处",
    )
    c.ok(
        "订单详情「改行」仍然只列在售商品（includeInactive = false 没被动）",
        "products(includeInactive = false)" in code(DETAIL_VM),
        "详情页那条路被改了",
    )
    c.ok(
        "派单池改单仍然只列在售商品（includeInactive = false 没被动）",
        "products(includeInactive = false)" in code(POOL_VM),
        "派单池那条路被改了",
    )
    c.ok(
        "商品列表接口的默认值没变（includeInactive = true，列表仍含下架商品）",
        "suspend fun products(includeInactive: Boolean = true)" in code(REPO)
        and 'includeInactive: Boolean = true' in code(APIS),
        "默认值被改成了 false（沽清商品会从列表里消失）",
    )
    c.ok(
        "AI 写工具的「下架」说法跟着行为一起改了（不许再说系统不会拦住）",
        "不会**拦住" not in ai and "拿它下单会被拦住" in ai,
        "说法还停在旧行为上 —— 模型会继续按旧说法回答用户",
    )
    c.ok(
        "AI 那条说法与角标同口径（说的是「已沽清」，不再自造「已下架」）",
        "带「已沽清」标记" in ai,
        "又出现了一个自己的说法",
    )

    # ---- 5. 文档与配对（判据自己也要有人盯）----
    c.ok("变更单 docs/changes/BUG-0017.md 存在", SPEC.exists(), "变更单没了")
    spec = read(SPEC)
    c.ok(
        "变更单写清了两份脚本的名字（判据 + 反向验证）",
        "_check_sold_out_block.py" in spec and "_reverse_verify_sold_out_block.py" in spec,
        "⑥/⑦ 里没有这份脚本的名字",
    )
    c.ok(
        "变更单的边界那条写了要保的东西（角标文案 / 可见范围可勾 / 两处 includeInactive）",
        "ProductSoldOutBadge" in spec and "ProductCheckList" in spec and "includeInactive" in spec,
        "边界清单缺了一项",
    )
    c.ok(
        "登记簿里有这一行（docs/changes/README.md）",
        "BUG-0017" in read(README),
        "README 里没有它 —— 下一个人会以为这条没人在做",
    )
    c.ok(
        "认领里有核心改动声明行（改核心区文件必须写）",
        "核心改动：backend/app/services/order_flow.py" in read(CLAIM),
        "AI_WORK_CLAIM.md 里没有声明行",
    )
    c.ok("这条红线配了反向验证脚本", (ROOT / REVERSE).exists(), f"找不到 {REVERSE}")

    # ---- 6. ⛔ 空转即停：判据自己的总项数 ----
    c.ok(
        f"判据总项数 ≥ {MIN_ITEMS}（少了就是判据被删空 —— 空转的检查比没有检查更危险）",
        c.total + 1 >= MIN_ITEMS,
        f"只有 {c.total + 1} 项",
    )

    if "--list" in sys.argv:
        print()
        print("  == 它到底在查什么 ==")
        print("     · 空转闸：扫到的 .kt ≥ 100、三份函数体抽得出来、判据自己的项数 ≥ 40")
        print("     · 选品页：整卡变灰（底色 + alpha）、加号 enabled=false + onClick 自己再拦、onAdd() 只有一个入口")
        print("     · 提交前：顶层谓词 soldOutLine 唯一定义、submit 只调它、文案指认那一行")
        print("     · 服务端：build_order_products 里 if not prod.is_active 必须 raise，且落在 pid 分支内、在售判定在成本快照之前")
        print("     · 别处不许变：角标唯一、可见范围页仍可勾、两处 includeInactive=false、列表默认值、AI 说法跟着改")
        print("     · 文档：变更单 / 登记簿 / 认领声明行 / 反向验证脚本在")

    return c.report("沽清（下架）的商品真的不能卖（L-35 / BUG-0017）")


if __name__ == "__main__":
    sys.exit(main())
