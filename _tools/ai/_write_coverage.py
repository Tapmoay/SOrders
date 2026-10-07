"""算「AI 写能力覆盖率」：后端 74 个写端点里，哪些已经有 AI 动作、哪些还没有。

### 为什么要有它
"还差多少个接口「这个问题，靠回忆答不准，靠肉眼读 6 个 Kotlin 文件更不准。
链路是 3 跳的：`AiWriteAction` → 处理器/`CrudSpec` → `AppRepository` 方法 → `Apis.kt` 的
Retrofit 函数 → 后端端点。这里把这条链还原出来：

  1. 解析 `Apis.kt`：`@POST("orders/{id}/exception")` ↔ `suspend fun markException(...)`
  2. 解析 `AppRepository.kt`：`api.markException(...)` ↔ `suspend fun markException(...)`
  3. 在 `ai/` 包里搜第 2 步那些 repo 方法名的调用
  4. 与后端 `docs/ai/write-endpoints.json`（74 条，ast 抓的）对账

### ⚠️ 「还剩 14 个」不是一个结论，除非每个都说得出为什么（v3.20 加）
早先的输出只有一句「未覆盖 14"，于是这 14 个到底是」还没做「还是」决定不做「，
只有写这份脚本的人知道。**下一个人（或下一轮的我）会把它们当成待办**，
甚至为了凑数字去做一个不该做的动作（比如让模型上传图片——它给不出文件）。

所以现在每个未覆盖端点都必须在 [EXCLUDED] 里有一条**写下来的理由**；
没有理由的会被单独列成「⚠️ 未覆盖且没有理由」，并在退出码上体现。
这条判据本身也要能反向验证：把某条理由删掉，它必须变红（见 `_reverse_verify_coverage.py`）。

用法：
    python _tools/ai/_write_coverage.py              # 汇总 + 未覆盖清单
    python _tools/ai/_write_coverage.py --module orders
    python _tools/ai/_write_coverage.py --check       # 有「没有理由」的就非零退出（给红线用）
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402

ROOT = repo_root()
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
APIS = AND / "data/remote/api/Apis.kt"
REPO = AND / "data/repo/AppRepository.kt"
AI = AND / "ai"
ENDPOINTS = ROOT / "docs/ai/write-endpoints.json"

# ------------------------------------------------------------------ 不做的理由
#
# 键 = (METHOD, 归一化路径)。**这个表只许加，不许为了凑覆盖率删。**
# 每一类都对应一条已经定过的规矩，不是「这个懒得做」。
EXCLUDED: dict[tuple[str, str], str] = {
    # 凭据：AI 不碰登录/注册。与风险分级无关——它连「该不该做」都不成立。
    ("POST", "auth/login"): "登录/注册：AI 不该碰凭据（v3.7 定的永久排除）",
    ("POST", "auth/token"): "登录/注册：AI 不该碰凭据（v3.7 定的永久排除）",
    # 登出（2026-09-19 补：这条端点是被"清单自己算"那个修法**照出来**的 —— 它加进来之后
    # 一直没进那张签入的表，所以覆盖率看不见它）。理由与凭据同类：
    # 登出是**会话动作**，模型替用户退出登录只会让他莫名其妙地被踢回登录页。
    ("POST", "auth/logout"): "登录/注册：AI 不该碰凭据与会话（v3.7 定的永久排除）",
    # 重置常用计数（2026-09-22 新增端点）。理由与"常用地点自动入库"同类：
    # 它清掉的是**统计**（"我用过它几次"），不是用户录入的业务事实；
    # 而模型替用户重置的后果是"用得越多越靠前"这件事**突然失效**，
    # 用户只会觉得"列表乱了"，查不出是谁干的。它属于**界面上的个人偏好动作**
    # （与「我的 → 基础设置」里那些开关同一类），不是一件可以申请的事。
    ("POST", "usage/reset"): "个人偏好：重置的是「常用度」统计（派生的排序依据），"
                             "不是业务事实；模型替用户清掉只会让排序静默失效",
    # 「我的 → 管下游的账」那颗开关（CHG-0076，2026-10-07 / 台账 L-39）。与上面那条同一类，
    # 但后果更实在：它是**批发商自己的偏好**（口径 ④ —— 派单员都不代设），关掉之后他那本
    # 下游账**当场空掉**；模型替他关掉，用户只会看到"账不见了"，
    # 而且他根本不知道有这么一回事（审计里那条虽然记了名字，但没人会去翻）。
    ("PATCH", "users/me/downstream-ledger"): (
        "个人偏好：「我的 → 管下游的账」是批发商自己的选择（连派单员都不代设）；"
        "模型替他关掉会让那本下游账当场空掉，而他不知道是谁关的"
    ),
    # ---- 下游定价（CHG-0077 → **CHG-0084 开给 AI**，2026-10-08）----
    # ⛔ 这三条原来挂在这里（口径：台账 L-38 五问之四「AI 先不开」）。2026-10-08 用户改口径：
    #    这一层价**开给批发商货主自己的 AI**（设 / 删 / 恢复三条都开，读侧两条一起开）。
    #    ⚠️ 开的只是"他给自己下游定价"这本账：入参里**没有 shipper_id**，写的永远是 current.id，
    #    派单员依旧不代设（那是后端 docstring 里的硬限制，不是手机端的礼貌）。
    #    判据不再靠这一条：三跳链路（apis → repo → ai/）自己会说话。
    # 用户明确说永久不做（目标④）。
    ("POST", "customers/merge"): "客户合并：用户明确说不需要、也没必要（目标④，永久排除）",
    # ⚠️ `POST /ai/telemetry` 一开始挂在这里，**2026-09-25 当天就挪走了** ——
    #    挪走的信号是判据自己报的：「写了『不做』的端点同时被算成已覆盖（两者不可能都对）」。
    #    原因是 Android 侧真的开始上报了（`AppRepository.reportAiCalls` → 三跳链路成立），
    #    于是它的正确归属是 `AI_DIRECT_USE`（AI 功能自己在用、但入口不在模型手上）。
    #    ⛔ 教训：**新端点先想清楚它属于哪一桶**；判据那条"两者不可能都对"就是为这个存在的。
    # 上传类：模型给不出文件。让它「申请上传」只会产生一张永远填不满的卡。
    ("POST", "orders/{}/address-image"): "上传类：要一个文件，模型给不出（v3.7 永久排除）",
    ("POST", "orders/{}/delivery-photos"): "上传类：要一个文件，模型给不出（v3.7 永久排除）",
    # ---- 订单结构两条（**CHG-0085 开给 AI**，2026-10-08 / 台账 L-54）----
    # 这两条原来挂在这里，理由**不是同一类**（当时就分开写在注释里了）：
    #   · 静默退回派单池（CHG-0039）：理由是这个动作的定义就是**货主无感** —— 事后没有第二条线索可核；
    #   · 转货（CHG-0042）：理由只是**输入形态**（多行 ＋ 选人，一轮问一件事装不下）—— 是排期，不是能力缺口。
    # 2026-10-08 用户口径把两条一起解掉（目标① 第二单）：转货的"多行"由 `lines` 数组 ＋
    # HIGH 档确认卡承担；静默退回"货主无感"这件事**落到卡片上写死**（卡片逐句说"货主端不会有任何变化"），
    # 并且它与「撤回派单」分成两个动作（合并的后果是货主收到一条他不该收到的通知）。
    # ⚠️ 两条都**只给派单员**（后端 `order:dispatch` / `order:recall`），货主连清单里都看不见。
    #    判据不再靠这一条：三跳链路（apis → repo → ai/）自己会说话。
    ("POST", "products/{}/image"): "上传类：要一个文件，模型给不出（v3.7 永久排除）",
    ("POST", "shipper/locations/image"): "上传类：要一个文件，模型给不出（v3.7 永久排除）",
    # 坐标类（v3.41 新增）：与上传类同一类问题 —— 这个参数**模型无从得知**。
    # 经纬度是"人在现场用 GPS 测出来的事实"，模型编一个数就会把司机导航到别的地方，
    # 而且**看上去完全正常**（一串合法小数）。让 AI "申请补导航"只会得到一张
    # 编造坐标的卡 —— 比不做更糟。
    #
    # ⚠️ 2026-09-20：**补导航开了口子，但坐标仍然不是模型给的** ——
    #    `orders.fill_nav` 让模型说的是"用共享地点库里的哪一个"（一个名字），
    #    坐标由 App 从库里取（`AiWriteArgs.strict` → `placeById`）。
    #    所以这一条从"不做"变成了"有动作"，而**原则没变**：
    #    模型全程碰不到经纬度。红线 `_check_ai_guardrails.py` 的
    #    「补导航只能引用库里已有的坐标」钉着这件事。
    #    `POST /places` 仍然不做：它是**新建**一个点，必然要有坐标，模型给不出。
    ("POST", "places"): "坐标类：经纬度是现场 GPS 测出来的事实，模型给不出、编一个会把司机带错（v3.41 永久排除）",
    # 导出类：产物是一个下载文件（要做也是「读+出表格」，不是写动作）。
    #
    # ⚠️ CHG-0078（2026-10-07 / 台账 L-43）之后这两条**分了家**，这里必须跟着分：
    #    · `POST /ledger/export-jobs` 挪进下面的 `AI_DIRECT_USE` —— 聊天里那颗「下载」
    #      按钮真的会调它（`ai/AiExportService.kt`），于是它既不再是"决定不做"，
    #      也不是"模型能调的动作"。挪走的信号还是判据自己报的那句
    #      「写了『不做』的端点同时被算成已覆盖（两者不可能都对）」。
    #    · `POST /stats/export` 留在这里，但旧理由已经不准了（聊天**现在真的能**把文件递给
    #      用户了）——准确的说法是：AI 那条路走的是 `export_sheet`（客户端现算）＋
    #      账本那条 `export_ledger`，这个端点在 Android 侧连 Retrofit 封装都没有，
    #      模型也没有"直接叫后端导一次"这种动作。
    ("POST", "stats/export"): (
        "导出类：产物是下载文件；App 侧的报表导出走的是 GET /reports/export，"
        "账本导出走 ledger/export-jobs —— 这个端点在 Android 侧连封装都没有，"
        "模型也没有「直接叫后端导一次」这种动作"
    ),
    # 司机端：目标③明确「司机端暂不开放 AI（以后只做查订单价格）」。
    ("POST", "orders/{}/complete"): "司机端动作：目标③司机端不开放 AI",
    ("POST", "orders/{}/complete-with-upload"): "司机端动作：目标③司机端不开放 AI（且含上传）",
    ("POST", "orders/{}/driver-ack"): "司机端动作：目标③司机端不开放 AI",
    ("POST", "orders/{}/driver-note"): "司机端动作：目标③司机端不开放 AI",
    # 功能上已被另一个端点覆盖（不是缺口，是重复路径）。
    ("DELETE", "notifications/{}"): "与 POST /notifications/batch-delete 同功能：AI 走批量删除那条路",
    # 埋点类：这个端点不改任何业务状态，它是 App 在用户点选共享地点时**自动**调的
    # 使用计数（"大家都去过这儿"+1，第 2 次起还会顺手把地点收进他自己的「我的地点」）。
    # 模型没有"申请记一次使用"这种动作，也不该有：模型看不见那个共享地点列表
    #（它是全库共享、按距离/关键词搜出来的），硬造一个动作只会让它去点一个它看不见的东西；
    # 而"把常用地点收进我的地点"是**用户点选**的副产物，不是一件可以申请的事。
    ("POST", "places/{}/use"): (
        "埋点类：App 在用户点选共享地点时自动调的「使用计数」（不改任何业务状态）；"
        "模型没有「申请记一次使用」这种动作，也不该有——它看不见那个共享地点列表"
    ),
    # 预订单的「使用计数」（2026-09-22）：与上面那条**同一类东西** ——
    # App 在用户点「用这张预设单下单」时自动记一次，它不改预设单、不改订单、不改钱，
    # 只是让这张预设单在列表里往前排。模型没有"点一下"这个动作，硬造一个只会让它
    # 去编一次"我用过了"（把排序搞乱，而且查不出是谁干的）。
    # ⚠️ 「建/改/删预设单」都有 AI 动作，那一头不受影响。
    ("POST", "order-templates/{}/use"): (
        "埋点类：App 在用户点「用这张预设单下单」时自动调的「使用计数」（不改任何业务状态）；"
        "模型没有「申请记一次使用」这种动作，也不该有——列表往前排的依据是**人**真的用过"
    ),
    # 开销分类名册（2026-09-20）：与商品/地点分类同一类**主数据维护**动作。
    # 不做 AI 动作的理由是"它决定的是**界面形态**，不是一件业务事实"：
    # `link_kind` 决定开销卡片上突出哪一项（车辆/司机/订单），改名会**级联**改掉一堆开销的分类，
    # 排序决定所有人看开销时左栏的顺序 —— 这三件事都是"配置"，用户要的是在分类管理页上
    #
    # ⚠️ **2026-09-23 这 12 条全部撤掉**（开销 / 运费 / 预订单三张名册，各 4 个端点）：
    #    用户那条硬规矩是「**人能操作、AI 就要能操作**」（原话：「所有的操作，主要是人能操作的
    #    他都可以操作」），而界面上分类管理页能做的四件事（建 / 改名 / 排序 / 删）AI 一件都没有 ——
    #    那就不是"用不上"，是**能力缺口**。
    #    当初担心的事（改名级联、删前要看挂着多少、排序要整份提交）不是"不能做"，
    #    而是"**卡片上必须写清楚**"：现在三组动作都带 `targetXxxCategory()`（`note` 里就是
    #    "这一类下有几笔开销 / 几条价目 / 几张预设单"）、删除是 HIGH 档、重排卡片把改前改后
    #    两份顺序都列出来。读侧也一并打开（`_read_coverage.EXCLUDED` 里那两条同理撤掉：
    #    看不见名册就没法重排、也没法在改名前报出影响面）。
    # ⚠️ 「记一笔开销」（`POST /expenses`）**已经有 AI 动作**，那一头不受影响。
    # ---- 运费分类名册（2026-09-21）：与开销分类同一类东西（界面配置）----
    # ---- 预订单分类名册（2026-09-22）：与开销/运费分类同一类东西（界面配置）----
    # ⚠️ 这一条是**本轮不做**（不是永久不做）：手动定价要同时决定"运费多少 / 算哪一类货 /
    #    要不要沉淀成价目"三件事，而金额是派单员当场判断出来的。AI 那条线正在整片重排
    #    （角色能力 + 写动作），等它收工再按"一次问一个问题"的口径做。
    ("POST", "orders/{}/price-freight"): (
        "本轮不开放：手动定价要同时决定金额/分类/要不要沉淀成价目，金额是派单员当场判断的；"
        "AI 写动作那条线正在重排，等它收工再按一次问一件事的口径做"
    ),
    # ---- 补联系信息（**CHG-0085 开给 AI**，2026-10-08 / 台账 L-54）----
    # 它原来挂在这里（台账 L-27 / L-28 / L-31，CHG-0057）的理由是"这是改单那张卡的子集 ＋ 只需要排期"。
    # 2026-10-08 开的时候顺带把口径分清了：这一条与「改单」**不是同一个动作** ——
    #   · 后端：`order:edit_contact`（scope = own）vs `order:edit`（派单员专属）；
    #   · 命令层：`update_order(contact_only=True)` 那一路对**终态单**（已送达/已撤销/已退货）也放行，
    #     而改单在终态单上会被拒 ——「货送完了才发现号码写错」正是这一扇门存在的理由；
    #   · 卡片：只能动四个联系字段，其余字段一个都不写。
    # ⛔ 与 `ORDERS_UPDATE`（改单）**两个动作都留着**：派单员走改单卡，货主走这一条（`roles = SHIPPER`）。
    # 采购单（FEAT-0013，2026-10-04）：**2026-10-07 CHG-0074（台账 L-42）起已开**。
    #
    # 这里以前关着四条的理由是"多行 + 一轮问一件事装不下"，而不是"用不上"（原话留在 git 历史里）。
    # 用户口径 m13365 ② 把那个理由解掉了：他要的正是「上传一张进货单照片 → AI 读出供应商与每行
    # → 确认卡 → 建采购单」—— 多行由**表格解析器 + 一张 HIGH 档确认卡**承担（与
    # products.apply_table 同一个解法），四个动作各管一件事：
    #   · POST     建单（库存 / 成本价 / 供应商欠款三处一起落，仍然由后端同一个事务完成）
    #   · PATCH    只改单头三样（供应商 / 单据日期 / 备注）；改行不在里面（后端是整份替换语义）
    #   · DELETE   撤单（三处一起回滚）
    #   · restore  把撤掉的单放回来
    # ⚠️ AI 侧只**调用**后端这一个入口，⛔ 不自己拼那三步、也⛔ 不写 inventory_movements。
    # 发票台账（FEAT-0014，2026-10-05 本轮不开放 → **CHG-0086 / 台账 L-55，2026-10-08 已开放**）：
    # 六条写端点（POST /invoices 登记、PATCH /invoices/{} 改票、POST /invoices/{}/issue 开具、
    # POST /invoices/{}/void 作废、DELETE /invoices/{} 撤票、POST /invoices/{}/restore 恢复）
    # 原来关着的理由是"票面金额直接进税汇、写动作那条线还没收工"——用户 2026-10-08 把这条排期
    # 解掉了。开之前先补了两件当时没有的东西，正好就是当初不敢开的那两条：
    #   · 「作废」与「撤票（进回收站）」在卡片上逐句分清：作废＝票留在台账里、退出税汇、票号还占着；
    #     撤票＝进回收站、之后还能原样放回来。两条各有各的 UNDO_NONE 理由（都撤不回来）；
    #   · 税额只有一个算法（`backend/app/services/tax_service.py::tax_of_amount`：合计 ÷ (1 + 税率)
    #     再倒推）：只给税率的票由 AI 当场算出来并**显式进 payload**，卡片上的数与库里存的数必须是
    #     同一个 —— 不许出现"卡片显示 130、库里存 155"。
    # ⚠️ 六条都只给派单员（后端要 ledger:edit），货主那份清单里一条都没有；票号唯一占号，
    #    所以定位时"票号"是唯一精确的键（其余条件撞上多张就列候选、拒绝动手）。
    # 挂账单位额度（FEAT-0015，2026-10-04）：**本轮不开放**（不是永久排除，也不是"用不上"）。
    # 信用额度是「这个单位还能赊多少」的上限 —— 直接决定一笔挂账收不收得住（L3 写），
    # 而且改额度的每一次都要留痕（动作码 ARREARS_UNIT_CREDIT_LIMIT，审计页有中文名）。
    # App 这边刻意**不开新路径**：额度就是挂账单位编辑表单上的一格，走既有的 PATCH。
    # ⚠️ 人工页本轮已经能建（带额度）/ 改额度 ⇒ 这不是能力缺口，是排期（写动作那条线重排中）。
    ("PATCH", "arrears-units/{}"): (
        "本轮不开放：额度是「这个单位还能赊多少」，直接决定挂账收不收得住（L3 写），"
        "而且每次改动都要留痕；额度复用挂账单位既有的 PATCH（不开新路径），"
        "写动作那条线收工后按一次问一件事的口径做"
    ),
    # 订单打折（CHG-0071 / 台账 L-34，2026-10-07）：**本轮不开放**（不是永久排除，也不是"用不上"）。
    # 与「手动定价」那条（`orders/{}/price-freight`）同一个形状：它是**派单员对着这一张单当场
    # 判断出来的让价**（减多少、打哪几行），而一张卡要同时定下方式（减百分比 / 抹零）＋ 值 ＋
    # 范围（整单 / 勾选若干行）＋ 理由四件事 —— "一轮问一件事"的写动作卡片装不下；
    # 而且它**改写每一行的金额**（钱落在行上，退货也按折后实付退），模型要是替用户定了这个数，
    # 用户只在合计上看得出来。AI 写动作那条线正在重排，等它收工后按同一口径做。
    # ⚠️ 人工入口本轮已经能用（订单详情页那颗「打折」）⇒ 这不是能力缺口，是排期。
    ("POST", "orders/{}/discount"): (
        "本轮不开放：让价要同时定方式（百分比/抹零）＋值＋范围（整单/勾选若干行）＋理由，"
        "一轮问一件事的写动作卡片装不下；而它改写每一行的金额（退货也按折后实付退），"
        "要等写动作那条线收工后按同一口径做"
    ),
    # 取消折扣是同一件事的另一面（把每一行金额还原成打折前的值，钱的反向操作）——
    # 与采购单/发票那几条同一规矩：要开一起开、要关一起关。
    ("DELETE", "orders/{}/discount"): (
        "同上（取消折扣）：把每一行金额还原成打折前的值，是让价的反向操作，"
        "与 POST 同一张卡的两面；等写动作那条线收工"
    ),
}

#: **AI 功能自己在用、但模型没法调**的写端点（第三个桶）。
#:
#: 为什么需要这一桶：`EXCLUDED` 的语义是"决定不做"，而 v3.32 的 AI 附件
#: （用户挂一份 Excel 让 AI 看）**做了**——只是入口不在模型手上：文件是**用户**
#: 在系统文件选择器里选的，App 上传解析后把表格正文随消息交给模型。
#: 模型侧根本没有"申请上传一个文件"这种动作可以存在，所以它既不是缺口、也不是"不做"。
#:
#: 这一桶必须配自己的反向约束（见下面的 direct_unused）：**声称"AI 在用"就必须真的在用**
#: ——ai/ 包里找不到对它的调用，这条声明就成了化石。
AI_DIRECT_USE: dict[tuple[str, str], str] = {
    # AI 调用计数上报（报告 §15 ② 的 AI_calls）：**AI 功能自己在用**（聊天页跑完一轮就报一次），
    # 但入口不在模型手上 —— ⛔ 模型没有"上报我跑了几次"这种动作，也**不该有**：
    # 让模型能调它等于让模型给自己的指标刷数，而指标一旦能被被观察者改就不再是证据。
    ("POST", "ai/telemetry"): (
        "AI 调用计数上报：聊天页跑完一轮自动调（模型侧没有「上报自己的调用次数」这种动作，"
        "也刻意不给 —— 给了就是让模型刷自己的指标）"
    ),
    ("POST", "files/parse-sheet"): (
        "AI 附件的入口：文件由用户在系统选择器里选，App 上传解析后把表格正文随消息交给模型"
        "（模型侧没有「申请上传」这个动作）"
    ),
    # 账本导出（CHG-0078，2026-10-07 / 台账 L-43）：AI 这条路**真的会建这个任务**，
    # 但建它的那一下是**用户点出来的**，不是模型调出来的 —— 模型手里的 `export_ledger`
    # 只发 `GET /ledger/accounts` 认人、回一张"配方"（配方在喂给模型之前就被摘掉了）；
    # 真正 `POST /ledger/export-jobs` 的是聊天里那颗「下载」按钮，走 `ai/AiExportService.kt`。
    # ⛔ 模型没有"替他消耗一次导出配额"这种动作，也**不该有** —— 那 20 次配额是用户自己的，
    #    模型一次都不该替他花（这与上面 telemetry 那条同一种形状：能发起 ≠ 能自己动手）。
    ("POST", "ledger/export-jobs"): (
        "账本导出：模型只认人（GET /ledger/accounts）并回一张配方，"
        "真正建任务那一下由用户点聊天里的「下载」触发（吃的是他自己当天 20 次的配额）"
        "—— 模型侧没有「替他花掉一次配额」这种动作"
    ),
}

# `@POST("orders/{id}/exception")` + 紧随其后的 `suspend fun markException(`
API_FN = re.compile(r'@(GET|POST|PATCH|DELETE|PUT)\("([^"]*)"\)[\s\S]{0,600}?fun\s+(\w+)\s*\(')
# AppRepository 里对 api 的调用：`api.orderApi.markException(...)` / `api.productApi.update(...)`
# ⚠️ 必须允许「api.子api.函数」两段：只写 `api\w*\.` 会贪婪吃掉 `api.orderApi`，抓出来的是子 api 名。
REPO_CALL = re.compile(r"\bapi(?:\.\w+)?\.(\w+)\s*\(")
# AppRepository 的方法（表达式体与块体都要认）：方法体里第一个 api 调用就是它对应的端点
REPO_METHOD = re.compile(
    r"(?:suspend\s+)?fun\s+(\w+)\s*\([^)]*\)[^\n{=]*[={]([\s\S]{0,900}?)(?=\n    (?:suspend\s+)?fun\s|\n\})",
    re.M,
)


def norm(path: str) -> str:
    """路径参数名两侧写法不同（后端 `{order_id}` / Retrofit `{orderId}`），统一成 `{}` 再比。"""
    return re.sub(r"\{[^}]*\}", "{}", path.strip("/"))


def api_paths() -> dict[tuple[str, str], str]:
    """(METHOD, 归一化路径) → Kotlin 函数名。"""
    out: dict[tuple[str, str], str] = {}
    for m in API_FN.finditer(APIS.read_text(encoding="utf-8")):
        out[(m.group(1), norm(m.group(2)))] = m.group(3)
    return out


def repo_to_api() -> dict[str, str]:
    """Api 函数名 → AppRepository 里的方法名（同一个端点的两种叫法）。"""
    src = REPO.read_text(encoding="utf-8")
    out: dict[str, str] = {}
    for m in REPO_METHOD.finditer(src):
        calls = REPO_CALL.findall(m.group(2))
        if calls:
            out.setdefault(calls[0], m.group(1))
    return out


def self_test_comment_blindness() -> None:
    """自检：**注释里的方法名不算覆盖**。

    为什么要有它（2026-09-19 审计）：覆盖率是"AI 写能力做完了没有"的唯一权威，而它的判据是
    "这个 repo 方法名在 ai/ 里出现过"。如果哪天有人把 `strip_comments` 去掉（或者换成
    不剥注释的写法），**在 KDoc 里写一句示例就能把某个写端点算成"已覆盖"** ——
    覆盖率虚高、不会红、下一个人会以为那个端点已经有 AI 动作。
    这条自检用一段合成源码当场比对：剥完注释后，注释里的 `markRead(` 必须**看不见**。
    """
    from _check_ai_guardrails import strip_comments  # 同目录脚本，模块级可导入

    sample = (
        "// 撤回走 repo.markRead(id)\n"
        "/* 也可以 repo.deleteLedgerEntry(x) */\n"
        "val n = 1\n"
    )
    names = set(re.findall(r"\b(\w+)\s*\(", strip_comments(sample)))
    leaked = names & {"markRead", "deleteLedgerEntry"}
    if leaked:
        raise SystemExit(
            f"❌ 覆盖率自检不通过：注释里的方法名被当成了真实调用（{sorted(leaked)}）——"
            "判据没剥注释，写一句 KDoc 示例就能把端点算成「已覆盖」。"
        )


def scan_called_names(src: str) -> set[str]:
    """**唯一的扫描入口**：剥掉注释之后，取源码里出现过的调用名。

    ⚠️ 自检与真实扫描都走这里（2026-09-19 审计）：如果自检自己调 `strip_comments`、
    而真实扫描走另一条路，那么"把剥注释删掉"这种破坏**自检照样绿** —— 我第一版就是这么写的，
    注入验证当场证明它抓不到。判据必须与被判据的代码**同一条路径**。
    """
    from _check_ai_guardrails import strip_comments  # 同目录脚本，模块级可导入

    return {m.group(1) for m in re.finditer(r"\b(\w+)\s*\(", strip_comments(src))}


def self_test_comment_blindness() -> None:
    """自检：**注释里的方法名不算覆盖**。

    为什么要有它：覆盖率是"AI 写能力做完了没有"的唯一权威，判据是"这个 repo 方法名在 ai/ 里
    出现过"。不剥注释时，**在 KDoc 里写一句示例**（"撤回走 `repo.markRead(id)`"）就能把对应写
    端点算成"已覆盖" —— 覆盖率虚高、不会红，下一个人会以为那个端点已经有 AI 动作了。
    """
    leaked = scan_called_names("// 撤回走 repo.markRead(id)\n/* repo.deleteLedgerEntry(x) */\nval n = 1\n")
    bad = leaked & {"markRead", "deleteLedgerEntry"}
    if bad:
        raise SystemExit(
            f"❌ 覆盖率自检不通过：注释里的方法名被当成真实调用了（{sorted(bad)}）——"
            "判据没剥注释，写一句 KDoc 示例就能把端点算成「已覆盖」。"
        )


def ai_mentioned_repos() -> set[str]:
    """ai/ 包里出现过哪些 repo 方法名（**只看真实代码，注释不算**，见自检的说明）。"""
    names: set[str] = set()
    for f in AI.glob("*.kt"):
        names |= scan_called_names(f.read_text(encoding="utf-8"))
    return names


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--module")
    ap.add_argument("--check", action="store_true", help="有「未覆盖且没有理由」就非零退出")
    args = ap.parse_args()

    # ⛔ **端点清单自己算，不读那份签入的 JSON**（2026-09-19 修）。
    #
    # 原来这里读 `docs/ai/write-endpoints.json`，而那份文件是**手工重跑**
    # `_dump_write_endpoints.py` 才更新的 —— 没有任何检查盯着它新不新鲜。
    # 实测：它是 2026-09-18 21:57 写下的，之后新加的写端点（本轮 `place-categories` 五个）
    # **一个都没进这张表**，于是这条"AI 写能力覆盖率"红线报「0 个真缺口」——
    # **假绿**。这正是本仓库反复栽的那类坑（清单过期 → 结论变成"没问题"，
    # 而 `_dump_write_endpoints.py` 自己的注释里就写着这句话）。
    #
    # 现在直接调那个脚本的 `handlers()`（同一份解析，不抄第二遍），
    # 端点永远与源码同步；签入的 JSON 只当"给人看的快照"。
    from _dump_write_endpoints import handlers as dump_handlers  # noqa: E402

    eps = dump_handlers()
    apis = api_paths()
    repo = repo_to_api()
    self_test_comment_blindness()
    mentioned = ai_mentioned_repos()

    rows = []
    unmatched = []
    for e in eps:
        path = norm(e["path"].replace("/api/v1", ""))
        key = (e["method"], path)
        fn = apis.get(key, "")
        # 有的端点在 App 侧直接就没有封装（例如登录/导出），那就是「根本没打算给 AI"
        if not fn:
            unmatched.append((e["method"], path))
        repo_fn = repo.get(fn, "") if fn else ""
        # 覆盖判据（⚠️ 这里踩过假阳性）：
        #   · 强证据：**repo 包装名**在 ai/ 包里出现过（handler 只能通过 repo 去调端点）；
        #   · 弱证据：Api 函数名在 ai/ 里出现过**且名字足够独特**。
        # 为什么必须加「足够独特」：`DELETE /notifications/{id}` 的 Api 函数就叫 `delete`，
        # 而 `delete` 这个词在 ai/ 包里到处都是（`MutableList.delete`、`list.delete`…），
        # 于是它被误判成「已覆盖"——**一个什么都没实现的端点被算进了覆盖率**。
        # 宁可少算：漏算会让人多干一遍活，虚报会让人以为干完了。
        strong = bool(repo_fn) and repo_fn in mentioned
        weak = len(fn) >= 8 and fn in mentioned
        covered = strong or weak
        rows.append((path, e["method"], fn, repo_fn, covered, e, strong, key))

    mod = lambda p: p.get("file", "?")  # noqa: E731
    if args.module:
        rows = [r for r in rows if args.module in (r[5].get("file") or "")]

    todo = [r for r in rows if not r[4]]
    weak_only = [r for r in rows if r[4] and not r[6]]
    # 「AI 自己在用、模型没法调」的那些：既不进 todo，也不算"已覆盖的动作"。
    direct = [r for r in rows if r[7] in AI_DIRECT_USE]
    direct_ids = {id(r) for r in direct}
    todo = [r for r in todo if id(r) not in direct_ids]
    # 未覆盖的必须**每一条都说得出为什么**：有理由的 = 决定不做；没理由的 = 真缺口。
    reasoned = [r for r in todo if r[7] in EXCLUDED]
    unexplained = [r for r in todo if r[7] not in EXCLUDED]

    # ---- 三条"这张表真的在被使用"的反向约束（否则它只是装饰）----
    #
    # ① 表里的键必须都还是真端点：端点改了名/删了，理由就成了化石，
    #    而化石比没有更糟（下一个人会以为「这条已经处理过了」）。
    all_keys = {r[7] for r in rows}
    stale = sorted(k for k in EXCLUDED if k not in all_keys)
    stale_direct = sorted(k for k in AI_DIRECT_USE if k not in all_keys)
    # ② 写了「不做」的端点**不能同时被算成已覆盖**：两者不可能都对。
    #    这一条专治"覆盖判据被改坏"（什么都算覆盖）——那时 todo 恒为空，
    #    理由表就永远不会被查，整个检查会安静地变成空转。
    contradiction = sorted((r[1], r[0]) for r in rows if r[4] and r[7] in EXCLUDED)
    # ③ 「AI 在用」的说法必须真的成立：ai/ 包里找不到对它的调用 → 声明是假的。
    #    这一条同时挡住了"为了消掉一条缺口，随手把它塞进 AI_DIRECT_USE"。
    direct_unused = sorted((AI_DIRECT_USE[r[7]], r[0]) for r in direct if not r[4])

    print(f"写端点共 {len(rows)}，已覆盖 {len(rows) - len(todo)}，未覆盖 {len(todo)}"
          f"（其中 {len(reasoned)} 条有写下来的「不做」理由，{len(unexplained)} 条是真缺口）")
    print(f"（其中 {len(unmatched)} 条在 Android 侧没有 Retrofit 封装 → 本来就不给 AI；"
          f"{len(weak_only)} 条是弱证据判定的，值得抽查）\n")
    if reasoned:
        print("已记录「不做」的（不是待办）：")
        for path, method, fn, repo_fn, _, e, _, key in sorted(reasoned, key=lambda r: r[0]):
            print(f"  {method:6s} /{path:48s} {EXCLUDED[key]}")
        print()
    if unexplained:
        print("⚠️ 未覆盖且**没有理由**——要么去做，要么在 _write_coverage.py 的 EXCLUDED 里写清为什么不做：")
        for path, method, fn, repo_fn, _, e, _, _ in sorted(unexplained, key=lambda r: r[0]):
            body = (e.get("body") or "").split(".")[-1]
            print(f"  {method:6s} /{path:48s} {mod(e):22s} body={body}")
        print()
    if stale:
        print("⚠️ 理由表里有**对不上任何端点**的条目（端点改名/删了？理由成了化石）：")
        for method, path in stale:
            print(f"  {method:6s} /{path:48s} {EXCLUDED[(method, path)]}")
        print()
    if contradiction:
        print("⚠️ 写了「不做」的端点**同时被算成已覆盖**（两者不可能都对：要么删理由，要么覆盖是假的）：")
        for method, path in contradiction:
            print(f"  {method:6s} /{path:48s} {EXCLUDED[(method, path)]}")
        print()
    if direct:
        print("AI 功能自己在用、但模型没法调的（不是缺口、也不是「不做」）：")
        for path, method, fn, repo_fn, _, _e, _, _key in sorted(direct, key=lambda r: r[0]):
            print(f"  {method:6s} /{path:48s} {AI_DIRECT_USE[(method, path)]}")
        print()
    if stale_direct:
        print("⚠️ 「AI 在用」表里有**对不上任何端点**的条目（端点改名/删了？）：")
        for method, path in stale_direct:
            print(f"  {method:6s} /{path:48s}")
        print()
    if direct_unused:
        print("⚠️ 声称「AI 功能自己在用」但 ai/ 包里找不到调用（这句话不成立）：")
        for why, path in direct_unused:
            print(f"  /{path:48s} {why}")
        print()

    if args.check and (unexplained or stale or contradiction or stale_direct or direct_unused):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
