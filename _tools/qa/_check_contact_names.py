"""红线：订单上的「收货人 / 下单人」——两个**名称** + 两个电话，从后端一路通到卡片与详情。

## 由来（用户 2026-09-20，对着代理下单页的截图）

> 这里分别再加 2 个信息，第一个是**收货人的名称**和**下单人的名称**。还有一个就是这个
> 下单人会根据自己的账号来进行自动填选，比如说是批发商或者说派单员，就会停到下单员这里，
> 然后自动填上去名称和电话号码全都填上去。普通货主的话，它自动填的也是自动写上去的。
> 那我们在这个卡片的信息会显示，进行一个收货人是谁、一个是下单人是谁，详情也好，
> 再详情也会显示这 2 个信息，这边的电话号码都会显示出来。

## 第二轮（2026-09-22，**「下单人」的来源被改掉了**）

> 「不是说下单吗？下单会**自动填入下单的人的名称和电话号码**，户主和批发商没关系，
> 因为他们是**自己下**嘛。但是这里有一点要注意的就是**派单员，他是代理下单**啊，
> 所以他**不能填写自己的名称和电话号码**，他要填的是**自动填选的是货主的**……
> **选择货主之后，他写的货主的信息就会自动地填入进去**，也就是名称和电话号码。」

⇒ **代理下单时「下单人」＝选中的那位货主**（不再＝当前登录账号）。判据收成一处纯函数
`ui/shipper/OrdererPrefill.kt::ordererContactFor`（有 JVM 单测），后端在 `create_order` 里
按同一口径**兜底**（老版本 App / AI 下单不会带这两栏）。

## 这条规则会被写坏成什么样（每一条都"不报错、不崩"）

| 写坏的方式 | 表现 |
|---|---|
| 只加了库里的列，`OrderOut` 没带出来 | 后端存了、客户端**永远拿不到**：卡片与详情还是空 |
| 只加了下单页的输入框，`OrderCreateRequest` 没带 | 用户填了名字，提交时**静默丢掉** |
| 只改了创建路径，PATCH 不认 | 派单员在「编辑订单」里改名字，保存后没变 |
| 收货人名称不从线路带出来 | 每次下单都要手打一遍（而线路里本来就记着这个人） |
| 下单人电话用会话里的 `username` 顶替 | 老数据/种子里的 username 可能是人名 → 填一个**打不通的号** |
| ⛔ **代理下单的下单人填成派单员自己** | 单子记成"派单员下的"，**界面上完全正常**；与货主对账时两个人都说不清 |
| ⛔ **换了货主，下单人还是上一位的姓名+电话** | 那是一串看起来很正常的号码，司机/货主照它打过去是**别人** |
| ⛔ **一位货主都没选时回落成当前登录账号** | 又回到上面第一条（首帧就填好了，选货主前提交就是错的） |
| ⛔ **临时货主也编一个电话出来** | 库里根本没有他的号 → 编出来的必须是别人的号 |
| 自动填在页面 / VM 里各写一遍 | 两个入口分叉：改一处漏一处，而单据归错人时没有任何提示 |
| 卡片与详情各拼一份「名字（电话）」 | 两边格式不一致；漏一个分支就少一行、且没有任何提示 |
| 详情页还写着「东家电话/老板电话」 | 与下单页、卡片、AI 三处用词不一致，用户问「收货人」对不上 |
| 搜索 `q` 只改了一条 OR 分支 | 卡片上明明写着名字，**搜这个名字搜不到**（派单员走的是另一支） |
| AI 改单的参数里没有这两个名字 | 用户说「把收货人改成张三」，模型只能答"改不了" |

## 判据

后端：模型两列 + `schema_bootstrap` 迁移 + 三个 schema（可写/可改/要出参）+
创建与 PATCH 两条写路径 + 搜索**两条** OR 分支 + 「下单人」兜底（只补两栏都空的那种单）+
「下单人就是货主本人时不进他自己的联系人名册」。
Android：`OrderDto` 两个字段、下单请求两个字段、下单页两个输入框、
自动填的判据**只有一处**（`OrdererPrefill.kt::ordererContactFor`：自己 / 选中的货主 / 临时货主 / 留空）、
收货人 ← 线路、卡片与详情都显示（共用 `contactWho`）。
AI：创建/改单两个动作认得它们，且目录里不再出现旧词。

⚠️ 注入式反向验证：`_tools/qa/_reverse_verify_contact_names.py`（每条都必须能红）。

用法：python _tools/qa/_check_contact_names.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))   # orders 源码并集（阶段 4 搬迁后）
from _airepo import orders_api_files, orders_api_source  # noqa: E402
#: 复用兄弟红线里剥注释的实现，不抄第二份。
from _check_pagination_wiring import strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
BACKEND = ROOT / "backend/app"

MODEL = BACKEND / "models/order.py"
BOOTSTRAP = BACKEND / "core/schema_bootstrap.py"
SCHEMA = BACKEND / "schemas/order.py"
API_MODULES = orders_api_files(ROOT)   # orders = 三个模块（阶段 4 搬迁后）
CONTACT_SVC = BACKEND / "services/shipper_contact_service.py"
BACKEND_TEST = ROOT / "backend/tests/test_order_boss_contact.py"

DTO = ANDROID / "data/remote/dto/Dtos.kt"
CREATE_SCREEN = ANDROID / "ui/shipper/OrderCreateScreen.kt"
CREATE_VM = ANDROID / "ui/shipper/OrderCreateViewModel.kt"
#: 「下单人 = 这一单的货主」这条判据的**唯一实现**（2026-09-22 第二轮收口）。
#: ⚠️ 名字里不带 `ORDERER` 单独一个词：下面那个 `RECEIVER, ORDERER = ...` 是**列名**，撞了会静默改掉它。
ORDERER_PREFILL = ANDROID / "ui/shipper/OrdererPrefill.kt"
ORDERER_PREFILL_TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ui/shipper/OrdererPrefillTest.kt"
CARD = ANDROID / "ui/common/OrderCard.kt"
DETAIL = ANDROID / "ui/order/OrderDetailScreen.kt"
DISP_SCREEN = ANDROID / "ui/dispatcher/DispatcherOrdersScreen.kt"
DISP_VM = ANDROID / "ui/dispatcher/DispatcherOrdersViewModel.kt"
AI_CATALOG = ANDROID / "ai/AiWrite.kt"
AI_ORDER = ANDROID / "ai/AiWriteOrderHandlers.kt"
AI_RES = ANDROID / "ai/AiResources.kt"

#: 这两个名字的**口径**：dongjia=收货人、boss=下单人。写反了的后果是"接货的人接到了下单人的电话"。
RECEIVER, ORDERER = "contact_dongjia_name", "contact_boss_name"


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


def main() -> int:
    c = Checker()
    model, bootstrap, schema = read(MODEL), read(BOOTSTRAP), read(SCHEMA)
    api = orders_api_source(ROOT)
    contact_svc = read(CONTACT_SVC)
    dto, screen, vm = read(DTO), read(CREATE_SCREEN), read(CREATE_VM)
    orderer = read(ORDERER_PREFILL)
    card, detail = read(CARD), read(DETAIL)
    disp_screen, disp_vm = read(DISP_SCREEN), read(DISP_VM)
    ai_catalog, ai_order, ai_res = read(AI_CATALOG), read(AI_ORDER), read(AI_RES)
    n_ok = 0

    # ---- ① 后端：列 + 迁移 + 三个 schema ----
    for col, cn in ((RECEIVER, "收货人"), (ORDERER, "下单人")):
        c.present(f"模型有 {col}（{cn}名称）", model, rf"{col}: Mapped\[str\] = mapped_column\(String\(64\)")
    c.present("模型里写清了口径（dongjia=收货人、boss=下单人）", model, r"dongjia=\*\*收货人\*\*[\s\S]{0,80}boss=\*\*下单人\*\*")
    for col in (RECEIVER, ORDERER):
        c.present(f"schema_bootstrap 能给旧库补上 {col}", bootstrap,
                  rf'"orders", "{col}",[\s\S]{{0,120}}ALTER TABLE orders ADD COLUMN {col}')
    c.present("OrderCreate 收这两个名称（否则下单填了也进不去）", schema,
              rf'class OrderCreate[\s\S]{{0,2500}}?{RECEIVER}: str = Field\(""[\s\S]{{0,400}}?{ORDERER}: str = Field\(""')
    c.present("OrderUpdate 改这两个名称（None = 不改）", schema,
              rf'class OrderUpdate[\s\S]{{0,1500}}?{RECEIVER}: str \| None[\s\S]{{0,400}}?{ORDERER}: str \| None')
    c.present("OrderOut 出这两个名称（**少了它客户端永远拿不到**）", schema,
              rf'class OrderOut[\s\S]{{0,6000}}?{RECEIVER}: str[\s\S]{{0,400}}?{ORDERER}: str')

    # ---- ② 后端：两条写路径 ----
    # ⚠️ 2026-09-22 第二轮：下单人那一栏写的是**兜底之后**的 `boss_name`（不再直接取 `body`）——
    #    锚点跟着实现搬，**规则没变**（"创建路径必须把两个名称都落库"）；兜底那一段的口径见下面 ②b。
    c.present("创建路径把两个名称都写进 Order(...)", api,
              rf'{RECEIVER}=body\.{RECEIVER}\.strip\(\)[\s\S]{{0,200}}?{ORDERER}=boss_name')
    c.present("PATCH 路径认这两个名称", api,
              rf'body\.{RECEIVER} is not None:\s*\n\s*order\.{RECEIVER} = body\.{RECEIVER}'
              rf'[\s\S]{{0,300}}?body\.{ORDERER} is not None:\s*\n\s*order\.{ORDERER} = body\.{ORDERER}')

    # ---- ②b 后端：「下单人」= 这一单的货主（2026-09-22 第二轮的口径，兜底那半边）----
    c.present("只有**代理下单**才兜底（货主自己下单一个字节都不补）", api,
              r"if target_shipper is not None and target_shipper\.id != current\.id:")
    # ⛔ 只补一半的后果：名字写"王老板"、电话却是货主账号那个号 —— 一个不存在的下单人。
    c.present("**两栏都空**才补（只空一栏不补）", api,
              r"if not boss_name and not boss_phone:\s*\n\s*boss_name = ")
    c.present("补的正是**这位货主**的姓名与电话", api,
              r'boss_name = \(target_shipper\.full_name or ""\)\.strip\(\)[\s\S]{0,200}?'
              r'boss_phone = \(target_shipper\.phone or ""\)\.strip\(\)')
    c.present("订单上写的是**兜底之后**的值（不是 `body` 原值）", api,
              r"contact_boss_phone=boss_phone[\s\S]{0,200}?contact_boss_name=boss_name")
    c.present("记联系人用的也是兜底之后的值（与订单上是同一个人）", api,
              r"upsert_boss_contact\(db, target_shipper_id, boss_phone, boss_name\)")
    c.present("⛔ 下单人就是货主本人时**不进他自己的联系人名册**", contact_svc,
              r"own_phone = db\.scalar\(select\(User\.phone\)[\s\S]{0,300}?"
              r"if own_phone and own_phone\.strip\(\) == phone:\s*\n\s*return")
    c.ok("有后端用例钉着这条路（兜底 / 只空一栏不补 / 不记自己 / 别人照记）",
         BACKEND_TEST.exists(), f"缺 {BACKEND_TEST.name}")
    if BACKEND_TEST.exists():
        t = read(BACKEND_TEST)
        # ⚠️ 锚要带上 `(client`：只锚 `def test_名字` 的话，把名字改成 `名字_v2` 照样绿
        #    —— 反向验证当场抓到的 MISS（前缀匹配把改名当成了"还在"）。
        c.present("用例钉着「两栏都空才补」", t, r"def test_代理下单只带一栏时不补另一栏\(client")
        c.present("用例钉着「货主自己下单不补」", t, r"def test_货主自己下单时后端不补下单人\(client")
        c.present("用例钉着「不许把货主记成他自己的联系人」", t,
                  r"def test_下单人就是货主本人时不进他自己的联系人名册\(client")
        c.present("用例钉着「下单人真的是别人时照记」（防止写成「一律不记」）", t,
                  r"def test_下单人真的是别人时联系人照记\(client")
        c.present("用例真的在断言（不是空函数）", t,
                  r'assert only_name\["contact_boss_phone"\] == ""')

    # ---- ③ 后端：搜索**两条** OR 分支都认得这两个名字 ----
    # ⚠️ 这一条是踩出来的：`GET /orders?q=` 对派单员与非派单员走两条不同的 OR 分支，
    #    第一版只改了一支 → 派单员搜"收货人名字"搜不到（卡片上明明写着）。
    blocks = [m.group(1) for m in re.finditer(r"or_\(([\s\S]{0,1500}?)\)\s*\n", api)
              # ⚠️ 2026-09-24 第 19 轮：`.like(term)` 变成 `.like(term, escape=LIKE_ESCAPE)`
              #    （`%`/`_` 要转义，见 `core/query_text`）→ 锚点跟着放宽到 `order_no.like(term`。
              if "order_no.like(term" in m.group(1)]
    missing = [i for i, b in enumerate(blocks) if RECEIVER + ".like" not in b or ORDERER + ".like" not in b]
    c.ok(f"搜单的每条 OR 分支都认得这两个名字（共 {len(blocks)} 条分支）",
         len(blocks) >= 2 and not missing, f"有 {len(missing)} 条分支没带名字（分支号 {missing}）")

    # ---- ④ Android：两个 DTO ----
    c.present("OrderDto 收这两个名称（列表与详情共用它）", dto,
              rf'data class OrderDto\([\s\S]{{0,4000}}?@SerialName\("{RECEIVER}"\)[\s\S]{{0,200}}?@SerialName\("{ORDERER}"\)')
    c.present("下单请求收这两个名称（否则填了不提交）", dto,
              rf'class OrderCreateRequest[\s\S]{{0,1500}}?@SerialName\("{RECEIVER}"\)[\s\S]{{0,200}}?@SerialName\("{ORDERER}"\)')
    c.present("改单请求也收这两个名称", dto,
              rf'class OrderUpdateRequest[\s\S]{{0,1200}}?@SerialName\("{RECEIVER}"\)[\s\S]{{0,200}}?@SerialName\("{ORDERER}"\)')

    # ---- ⑤ Android：下单页两个输入框 + 「下单人填谁」的判据（2026-09-22 第二轮改过）----
    # ⚠️ 锚点要认**两种形态**：2026-09-22 起这一页走共用表单行（`FormInputRow(label = "收货人名称")`），
    #    原来是 `OutlinedTextField(label = { Text("收货人名称") })`。判据的**本意**是
    #    "这两个字段在这一页上真的存在"，不是"它必须长成一个描边输入框" —— 只认旧形态的话，
    #    下一个人按规范改成共用行就会**平白报红**，然后他会把这条判据删掉。
    c.present("下单页有「收货人名称」输入框", screen,
              r'label = (?:"收货人名称"|\{ Text\("收货人名称"\) \})')
    c.present("下单页有「下单人名称」输入框", screen,
              r'label = (?:"下单人名称"|\{ Text\("下单人名称"\) \})')
    c.present("代理下单时占位文案说「选择货主后自动填入」（不是「默认当前账号」）", screen,
              r'if \(vm\.proxyMode\) "选择货主后自动填入"')

    # ⚠️ 清单**自己算**（全源码树扫一遍）：这一条要抓的恰恰是"别处又冒出一份判据"。
    defs = [
        p.relative_to(ROOT).as_posix()
        for p in sorted(ANDROID.rglob("*.kt"))
        if "fun ordererContactFor(" in p.read_text(encoding="utf-8")
    ]
    c.ok(f"「下单人填谁」**只有一处实现**（共 {len(defs)} 个文件）",
         defs == ["android/app/src/main/java/com/tapmoay/sorders/ui/shipper/OrdererPrefill.kt"],
         f"实际在：{defs}")
    c.present("货主 / 批发商自己下单 → 填自己", orderer,
              r"if \(!proxyMode\) return OrdererContact\(ownName")
    c.present("临时货主 → 只填姓名，**电话留空**（库里没有他的号，编一个只能是别人的）", orderer,
              r'if \(temp\.isNotEmpty\(\)\) return OrdererContact\(temp, ""\)')
    # ⛔ 这一条是整轮的核心：代理下单**一位货主都没选**时留空，绝不回落成派单员自己。
    c.present("一位货主都没选 → **留空，绝不回落成当前登录账号**", orderer,
              r'val s = shipper \?: return OrdererContact\("", ""\)')
    c.present("选了货主 → 用这位货主的姓名与电话", orderer,
              r"return OrdererContact\(s\.fullName\.trim\(\), s\.phone\.trim\(\)\)")

    c.present("VM 有 `proxyMode` 标记（登录角色是派单员）", vm,
              r'proxyMode = s\?\.role == "dispatcher"')
    c.present("代理下单**不预填自己**（账号预填被 `if (!proxyMode)` 包住）", vm,
              r"if \(!proxyMode\) \{[\s\S]{0,400}?prefillOrdererFromSelf\(")
    c.present("下单人按**账号资料**自动填（不是拿 username 当电话）", vm,
              r"repo\.me\(\)[\s\S]{0,200}?prefillOrdererFromSelf\(")
    c.absent("自动填没有把会话里的 username 当电话用", vm, r"prefillOrdererFromSelf\([^)]*username")
    c.present("换货主时重算下单人（选了谁就是谁）", vm,
              r"if \(proxyMode\) applyOrdererFromShipper\(id\)")
    c.present("名册里查不到就**单取一位货主**（预订单/带参直达那一页名册还是空的）", vm,
              r"container\.repo\.userById\(id\)")
    c.present("异步回包带校验（这期间换了货主就不认这一条）", vm,
              r"if \(proxyMode && shipperId == id && tempShipperName == null\)")
    c.present("落笔只有一处（`writeOrderer`，两个入口共用）", vm,
              r"private fun writeOrderer\(c: OrdererContact[\s\S]{0,400}?bossName = c\.name"
              r"[\s\S]{0,120}?bossPhone = c\.phone")
    c.present("收货人名称从选中的线路带出来", vm, r"applyAddress[\s\S]{0,700}?receiverName")
    c.present("init 里的自动填真的被调到", vm, r"init \{[\s\S]{0,1200}?prefillOrdererFromSelf\(")

    c.ok("「下单人填谁」有 JVM 单测", ORDERER_PREFILL_TEST.exists(), f"缺 {ORDERER_PREFILL_TEST.name}")
    if ORDERER_PREFILL_TEST.exists():
        t = read(ORDERER_PREFILL_TEST)
        c.present("单测钉着「一个货主都没选 → 空」", t,
                  r"派单员一个货主都没选 —— 留空，绝不回落成派单员自己")
        c.present("单测钉着「临时货主 → 电话留空」", t, r"派单员选临时货主 —— 只填姓名，电话留空")
        c.present("单测钉着「换货主 → 电话跟着换」", t, r"派单员换了货主 —— 电话跟着换")

    # ---- ⑥ Android：卡片与详情都显示，格式只有一份 ----
    n_who = len(re.findall(r"fun contactWho\(", card))
    c.ok("「名字（电话）」的拼接只有一份实现（contactWho）", n_who == 1, f"找到 {n_who} 处定义")
    uses = len(re.findall(r"contactWho\(", card)) + len(re.findall(r"contactWho\(", detail))
    c.ok(f"卡片与详情都调它（共 {uses} 处调用）", uses >= 3, "少了就是有一处自己拼了一遍")
    c.present("卡片上有「收货人」这一行", card, r'"收货人" to contactWho\(order\.contactDongjiaName, order\.contactDongjiaPhone\)')
    c.present("卡片上有「下单人」这一行", card, r'"下单人" to contactWho\(order\.contactBossName, order\.contactBossPhone\)')
    c.present("详情页有「收货人」", detail, r'"收货人 " \+ who')
    # ⚠️ 锚点认两种形态：2026-09-22 起详情页那一行不再是 `InfoRow("下单人", who)`
    #    （改成可点击拨打、电话绿色、点了先弹确认，所以自己画了一行）。
    #    判据的**本意**是"详情页上真的有『下单人』这一行"，不是"它必须用 InfoRow 画"。
    c.present("详情页有「下单人」", detail, r'("下单人"|InfoRow\("下单人", who\))')

    # ---- ⑦ 用词统一：旧词「东家电话 / 老板电话」在任何界面与 AI 目录里都不许再出现 ----
    for name, text in (("下单页", screen), ("编辑订单弹窗", disp_screen), ("订单详情", detail),
                       ("订单卡片", card), ("AI 动作目录", ai_catalog), ("AI 资源名册", ai_res)):
        c.absent(f"{name}里没有旧词「东家电话/老板电话」", text, r"东家电话|老板电话")

    # ---- ⑧ 派单员的「编辑订单」也要能改名字 ----
    c.present("编辑弹窗有这两个输入框", disp_screen, r'label = \{ Text\("收货人名称"\) \}[\s\S]{0,1200}?label = \{ Text\("下单人名称"\) \}')
    c.present("保存时把两个名字一起提交", disp_vm,
              rf'contactDongjiaName = editDongjiaName[\s\S]{{0,200}}?contactBossName = editBossName')

    # ---- ⑨ AI：创建/改单两个动作认得它们，handler 真的带上 ----
    c.present("AI 创建订单的动作有这两个名称参数", ai_catalog,
              r'AiWriteParam\("name_dongjia"[\s\S]{0,600}?AiWriteParam\("name_boss"')
    c.present("AI 改单的动作有这两个名称参数", ai_catalog,
              r'AiWriteParam\("dongjia_name"[\s\S]{0,600}?AiWriteParam\("boss_name"')
    c.present("AI 创建订单的 payload 带上它们", ai_order,
              rf'put\("{RECEIVER}", nameDongjia\)[\s\S]{{0,200}}?put\("{ORDERER}", nameBoss\)')
    c.present("AI 改单的改动清单带上它们", ai_order,
              rf'Triple\("dongjia_name", "收货人名称", "{RECEIVER}"\)[\s\S]{{0,200}}?Triple\("boss_name", "下单人名称", "{ORDERER}"\)')
    c.present("AI 资源名册认得这两个键（确认卡才显示得出改前改后）", ai_res,
              rf'"{RECEIVER}" to "收货人名称"[\s\S]{{0,300}}?"{ORDERER}" to "下单人名称"')

    # ---- ⑩ 反空转 ----
    checked = {
        "后端文件": sum(1 for p in (MODEL, BOOTSTRAP, SCHEMA, *API_MODULES) if p.exists()),
        "Android 文件": sum(1 for p in (DTO, CREATE_SCREEN, CREATE_VM, CARD, DETAIL, DISP_SCREEN, DISP_VM) if p.exists()),
        "AI 文件": sum(1 for p in (AI_CATALOG, AI_ORDER, AI_RES) if p.exists()),
    }
    c.ok(f"该查的文件都认出来了（{checked}）", all(v > 0 for v in checked.values()))

    print()
    if c.fails:
        print(f"❌ {len(c.fails)} 项不达标：")
        for f in c.fails:
            print("   - " + f)
        return 1
    print(f"✅ 全部 {c.passes} 项通过：收货人/下单人从库到卡片/详情/AI 是一条通的路。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
