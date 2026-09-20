"""红线：账本「**记一笔账**」的规矩（2026-09-20 用户第七轮）。

## 用户原话（这一页就是照它做的）

> 「他这个**手动记账**的逻辑不对 —— **这个商品是可以在现有的商品库进行选择的**。
>  这一般情况下，假如**订单没有走、但是有一笔账是这样存在的**；**未注册的话，也可以直接填**，
>  它是可以显示到一个列表上、**会自动帮他注册一个临时账户**，也就相当于一个普通账户吧。
>  然后时间备注也是可以填的；**他只要填数量、对应的价格是会有的**，但是可能单价是不一样的 ——
>  **单价是可以进行改的**，也就是预售价可以单独调整。」

## 这条规则会被写坏成什么样（都不是假想）

| 写坏的方式 | 表现 |
|---|---|
| 商品名又变回**手打** | 「红富士苹果 / 红富士 / 苹果」在库里是三个名字，库存与报表按名字分组就成了三行；单价、单位本来也都挂在商品上 |
| 提交时不带 `product_id` | 账本行与商品库脱钩 —— 报表按商品聚合时它进不了任何一行，**两边都不报错** |
| 选品页退化成"多选" | 一笔账只记一件商品，挑了两件却只写进去一件（或写进去一半），用户核对时看不出来 |
| 单价不可改 / 改完又被覆盖 | 用户要的是"预售价可以单独调整"；换货主时把用户手改的价拽走，等于**悄悄改了他报的价** |
| 「未注册」那条路被删掉 | 没建过档的客户（"来收一趟货"）就记不了账 —— 这是**需求本身**没做 |
| 名字填了却又带上 `shipper_id` | 后端直接 400（`请只指定 shipper_id 或 temp_shipper_name 之一`），表现是"点了保存没反应" |
| 名册搜索退回**本地过滤**手里这一页 | `/users` 一页上限 500，第 501 个货主在客户端根本不存在 → 用户去填一个临时货主 → **同一个人两本账** |
| 客户端自己算 `total` 传上去 | Double 乘法会带出 `36.900000000000006` 这种尾数进库（"同一个数两处算法"，账目对不上） |
| 从记账页回来**不重取** | 刚记的那笔不在列表里 → 用户以为没存上 → 再记一遍（账真的多了一笔） |

用法：python _tools/qa/_check_ledger_manual_entry.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _check_pagination_wiring import strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
CREATE = ANDROID / "ui/dispatcher/LedgerCreateScreen.kt"
SCREEN = ANDROID / "ui/dispatcher/DispatcherLedgerScreen.kt"
VM = ANDROID / "ui/dispatcher/DispatcherLedgerViewModel.kt"
ROUTES = ANDROID / "ui/nav/Routes.kt"
NAVGRAPH = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/nav/NavGraph.kt"
PICKER = ANDROID / "ui/common/ProductPicker.kt"
ORDER_CREATE = ANDROID / "ui/shipper/OrderCreateScreen.kt"
USER_SEARCH = ANDROID / "core/UserSearch.kt"
REPO = ANDROID / "data/repo/AppRepository.kt"
LEDGER_API = ROOT / "backend/app/api/v1/ledger.py"
LEDGER_SCHEMA = ROOT / "backend/app/schemas/ledger.py"

#: 反空转：认出的文件数与断言数低于下限就先报错（"检查在空转"比"没有检查"更糟）
MIN_FILES = 8


def read(p: Path) -> str:
    if not p.exists():
        raise SystemExit(f"找不到文件：{p}（改名/移动了？本脚本的断言要跟着改）")
    return strip_comments(p.read_text(encoding="utf-8"))


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


def block_after(src: str, start: int) -> str:
    """从 `{`（start 指向它）开始，按花括号配平取出块内容。"""
    depth = 0
    for i in range(start, len(src)):
        ch = src[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return src[start + 1 : i]
    return src[start + 1 :]


def fun_body(src: str, header: str) -> str:
    """取 `header` 那个声明的**函数体**（按花括号配平）。

    为什么要它：`"shipperId = null"` 这种判据用「往后数 400 个字符内找得到就算数」去找，
    会被**后面那个同名函数**里的同一句蒙混过去（反向验证当场抓到：把 `pickTempName` 里那句删掉，
    400 字内 `clearShipper` 里的那句还在，判据照样绿）。判据必须锚在**那一个函数体**里。
    """
    i = src.find(header)
    if i < 0:
        raise SystemExit(f"找不到声明：{header!r}（改名了？本脚本的断句要跟着改）")
    brace = src.find("{", i)
    if brace < 0:
        raise SystemExit(f"{header!r} 后面没有函数体？")
    return block_after(src, brace)


def main() -> int:
    c = Checker()
    files = {
        "create": read(CREATE),
        "screen": read(SCREEN),
        "vm": read(VM),
        "routes": read(ROUTES),
        "nav": read(NAVGRAPH),
        "picker": read(PICKER),
        "order_create": read(ORDER_CREATE),
        "user_search": read(USER_SEARCH),
        "repo": read(REPO),
        "backend": read(LEDGER_API),
        "schema": read(LEDGER_SCHEMA),
    }
    c.ok(f"认得出这一块的 {len(files)} 个文件（少了就先报错，别安静地跳过）", len(files) >= MIN_FILES)
    create = files["create"]

    # ---- ① 一页一件事：记账是**单独一页**，账本页里不留第二份 ----
    print("\n① 记账 = 单独一页（弹窗里套不下全屏选品层）")
    c.present("有「记一笔账」的路由", files["routes"], r'const val LEDGER_CREATE =')
    c.present("路由在 NavGraph 里注册了", files["nav"], r"composable\(Routes\.LEDGER_CREATE\)")
    c.present("账本页的「记账」按钮去那一页（不是自己弹窗）",
              files["nav"], r"onCreateEntry = \{ navController\.navigate\(Routes\.LEDGER_CREATE\) \}")
    c.present("新页是整页表单（有 Scaffold 与返回）", create, r"fun LedgerCreateScreen\(")
    c.absent("账本页**不再**内嵌记账弹窗（`vm.showCreate`）", files["screen"], r"vm\.showCreate|showCreate =")
    c.absent("账本页**不再**有记账草稿字段", files["screen"], r"vm\.draft(ShipperName|Product|Qty|Price|Date|Note)")
    c.absent("VM 里**不再**有第二份 create()/openCreate()（同一件事不留两份）",
             files["vm"], r"fun openCreate\(|fun create\(\s*\)")
    c.absent("VM 里不再有记账草稿状态", files["vm"], r"var draftShipperName|var draftProduct")

    # 回来要重取：不然"刚记的那笔看不见" → 用户再记一遍
    c.present("账本页回来时重取一次（LaunchedEffect 调 vm.onEnter()）",
              files["screen"], r"LaunchedEffect\(Unit\) \{ vm\.onEnter\(\) \}")
    c.present("VM 的 onEnter() 真的重新拉数与账户", files["vm"], r"fun onEnter\(\)[\s\S]{0,400}?load\(\)[\s\S]{0,200}?loadAccounts\(\)")
    c.present("第一次进这一页不重复拉（init 刚拉过）", files["vm"], r"private var entered = false")

    # ---- ② 商品：**只能从商品库选** ----
    print("\n② 商品只能从商品库选（那一份 UI 只有一处）")
    c.present("用共用的选品页（不是自己画的商品列表）", create, r"ProductPickerSheet\(")
    c.present("选品页是**单选**（一笔账只记一件商品）", create, r"single = true")
    c.present("选品页本身支持单选，**默认仍是多选**（下单那边一个字不变）",
              files["picker"], r"single: Boolean = false")
    c.absent("下单页没有偷偷变成单选（它还是要一次挑多件）",
             files["order_create"], r"ProductPickerSheet\([\s\S]{0,400}?single = true")
    c.present("单选模式下再挑一件是**换掉**（先清空再放）", files["picker"], r"if \(single\) picked\.clear\(\)")
    c.present("商品名只有「从商品库里挑了一件」这一处写入",
              fun_body(create, "fun pickProduct("), r"productName = line\.name")
    c.absent("页面里**没有**写商品名的输入框（那等于又能手打）",
             create, r"vm\.productName = ")
    c.present("提交体带上 product_id（否则账本行与商品库脱钩）", create, r"productId = productId")
    c.present("没选商品不许提交", create, r'if \(productId == null\) \{\s*error = "请从商品库里选商品"')

    # ---- ③ 单价：自动带出 + 可改 + 改过的不被覆盖 ----
    print("\n③ 单价：选商品时自动带出，用户可以改（预售价单独调整）")
    c.present("专属价优先、默认售价兜底（与下单页同一条口径）",
              create, r"priceRules\[p\.id\]\?\.specialUnitPrice \?:\s*p\.defaultUnitPrice")
    c.present("只认**当前货主**那份专属价（对不上就回默认价）", create, r"priceRulesShipper != sid")
    c.present("挑到商品就把价带进输入框", create, r"price = trimMoneyZeros\(line\.price\)")
    c.present("价框可编辑（走 InputRules.priceInput）", create, r"vm\.price = InputRules\.priceInput\(it\)")
    c.present("用户改过的价**不被拽走**（判据 = 当前价是否还等于上次自动带出的那个）",
              fun_body(create, "private fun repriceIfAuto("),
              r"if \(autoPrice != null && price != autoPrice\) return")
    c.present("自动带入的价用 trimMoneyZeros（编辑框里不许显示 12.5000）",
              create, r"price = trimMoneyZeros\(priceFor\(p\)\)")
    c.present("换**注册货主**之后重算价（他那份专属价与默认价不一样）",
              fun_body(create, "private fun reloadPriceRules("), r"repriceIfAuto\(\)")
    c.present("换成**未注册的名字**也要重算（临时货主没有专属价——真机抓到的错价）",
              fun_body(create, "fun pickTempName("), r"repriceIfAuto\(\)")
    c.present("清空记账对象同样重算", fun_body(create, "fun clearShipper("), r"repriceIfAuto\(\)")
    n_def = len(re.findall(r"private fun repriceIfAuto", create))
    n_call = len(re.findall(r"repriceIfAuto\(\)", create))
    c.ok("重算只有一处实现（定义 1 处 + 三个入口各调一次 = 总共 4 处，不各写一遍）",
         n_def == 1 and n_call == 4,
         f"定义 {n_def} 处、出现 {n_call} 处")
    c.present("合计 = 数量 × 单价（当场看得见）", create, r"fun total\(\): Double = \(qty\.toIntOrNull\(\)")

    # ---- ④ 货主：注册的 or 未注册（填了名字 = 临时账户） ----
    print("\n④ 货主：选已注册的，或直接填未注册的名字")
    c.present("两个字段**互斥**（同时传后端直接 400）",
              fun_body(create, "fun submit("),
              r"tempShipperName = if \(shipperId == null\) name else null")
    c.present("填了名字就清掉注册账号",
              fun_body(create, "fun pickTempName("), r"shipperId = null")
    c.present("「用过的临时货主」列出来（用户：「它会显示到列表上」）",
              create, r"visibleTempNames\(\)")
    c.present("那份名单来自后端（账本+订单里出现过的名字）",
              create, r"container\.repo\.tempShipperNames\(\)")
    c.present("名册搜索走**服务端** `?q=`（本地过滤找不到第 501 个人）",
              create, r'usersPage\(role = "shipper", q = kw\)')
    c.present("本地过滤只用于那份临时名清单，且走唯一实现", create, r"UserSearch\.filter\(tempNames")
    c.present("人名搜索框走共用组件（同源提示语 + 后 4 位）", create, r"SearchField\(")
    c.present("名册被截断要说出来（读了响应头，不许丢掉）",
              create, r"rosterTruncated = page\.meta\.hasMore")
    c.present("截断时界面上真的有那句话", create, r"if \(vm\.rosterTruncated")
    c.present("搜索失败**不许**退回空列表（那等于说「没有这个人」）",
              create, r"error = \"搜索失败：\"[\s\S]{0,200}?shipperHits = null")

    # ---- ⑤ 钱不自己算（同源那一课的教训） ----
    print("\n⑤ 金额不由客户端算好传上去")
    c.present("提交**不传 total**（后端用 Decimal 算 unit_price × quantity）",
              create, r"total = null")
    c.absent("客户端没有自己乘出 total 传上去", create, r"total = \(q|total = qty")
    c.present("后端仍然是唯一算法（没被这轮改掉）",
              files["backend"], r"total = body\.unit_price \* body\.quantity")
    c.present("后端只收 MANUAL 来源（手工账不许伪装成订单账）",
              files["backend"], r"手工记账只能记为「手动」来源")
    c.present("后端允许 product_id 一起进来（这一轮没加新端点，本来就收）",
              files["schema"], r"product_id: int \| None = None")

    # ---- ⑥ 反空转：认出的关键锚点够不够 ----
    print("\n⑥ 反空转")
    anchors = [
        r"class LedgerCreateViewModel",
        r"pickShipper\(",
        r"pickProduct\(",
        r"visibleShippers\(\)",
        r"shipperHint\(\)",
    ]
    missing = [a for a in anchors if not re.search(a, create)]
    c.ok(f"{len(anchors)} 个关键锚点都在（缺一个说明判据失配）", not missing, f"缺：{missing}")

    print("\n" + "=" * 60)
    if c.fails:
        print(f"❌ {len(c.fails)} 项不通过：")
        for f in c.fails:
            print("   - " + f)
        return 1
    print(f"✅ 全部 {c.passes} 项通过：记账单独一页、商品只能从商品库选、单价可改、未注册货主自动成临时账户。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
