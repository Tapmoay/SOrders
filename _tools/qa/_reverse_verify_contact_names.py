"""反向验证「收货人 / 下单人」那条红线**真的会红**。

为什么这块必须反向验证：这条链路横跨**四层**（库 → 后端出参 → 客户端 DTO → 界面），
而断在任何一层的表现都是同一个 —— **界面上少一样东西，没有任何报错**：
列加了但 `OrderOut` 没带、输入框加了但请求没带、创建带了但 PATCH 没带、
搜索只改了一条 OR 分支、自动填拿 `username` 当电话。

「判据本身是不是在检查」只能靠注入法证明：每条注入都改坏**一处**，红线必须点出**那一条**。

用法：python _tools/qa/_reverse_verify_contact_names.py    # 全部报红 → 退出码 0
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_contact_names.py"

ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
BACKEND = ROOT / "backend/app"

MODEL = BACKEND / "models/order.py"
BOOTSTRAP = BACKEND / "core/schema_bootstrap.py"
SCHEMA = BACKEND / "schemas/order.py"
API = BACKEND / "api/v1/orders.py"
#: orders 的**查询组**（2026-09-24 整改阶段 4 纯搬迁：列表/待派计数/详情搬去了 orders_query.py）
API_Q = BACKEND / "api/v1/orders_query.py"
CONTACT_SVC = BACKEND / "services/shipper_contact_service.py"
BACKEND_TEST = ROOT / "backend/tests/test_order_boss_contact.py"
DTO = ANDROID / "data/remote/dto/Dtos.kt"
CREATE_SCREEN = ANDROID / "ui/shipper/OrderCreateScreen.kt"
CREATE_VM = ANDROID / "ui/shipper/OrderCreateViewModel.kt"
ORDERER_PREFILL = ANDROID / "ui/shipper/OrdererPrefill.kt"
CARD = ANDROID / "ui/common/OrderCard.kt"
DETAIL = ANDROID / "ui/order/OrderDetailScreen.kt"
AI_CATALOG = ANDROID / "ai/AiWrite.kt"

#: (说明, 文件, 原文, 替换成, 期望变红的那条检查名关键词)
MUTATIONS = [
    (
        "库里的列加了，但 OrderOut 没带出来（客户端永远拿不到）",
        SCHEMA,
        '    contact_dongjia_name: str = ""\n    contact_boss_name: str = ""\n',
        "",
        "OrderOut 出这两个名称",
    ),
    (
        "创建订单时不写这两个名称（下单填了也进不去）",
        API,
        "        contact_dongjia_name=body.contact_dongjia_name.strip(),\n"
        "        contact_boss_name=boss_name,\n",
        "",
        "创建路径把两个名称",
    ),
    (
        "PATCH 不认这两个名称（派单员编辑订单时改了没变）",
        API,
        "    if body.contact_dongjia_name is not None:\n"
        "        order.contact_dongjia_name = body.contact_dongjia_name\n"
        "    if body.contact_boss_name is not None:\n"
        "        order.contact_boss_name = body.contact_boss_name\n",
        "",
        "PATCH 路径认这两个名称",
    ),
    (
        "搜索只改了非派单员那一支（派单员搜收货人名字搜不到）",
        API_Q,
        "                    Order.contact_dongjia_name.like(term, escape=LIKE_ESCAPE),\n"
        "                    Order.contact_boss_name.like(term, escape=LIKE_ESCAPE),\n"
        "                    Order.contact_dongjia_phone.like(term, escape=LIKE_ESCAPE),\n"
        "                    Order.contact_boss_phone.like(term, escape=LIKE_ESCAPE),\n",
        "",
        "搜单的每条 OR 分支",
    ),
    (
        "OrderDto 少了这两个字段（卡片与详情都拿不到）",
        DTO,
        '    /** 收货人名称（到现场接货的人）—— 与 [contactDongjiaPhone] 一一对应。空 = 老单没记过名字。 */\n'
        '    @SerialName("contact_dongjia_name") val contactDongjiaName: String = "",\n'
        '    /** 下单人名称（下这一单的人：货主本人 / 代下单的派单员）—— 与 [contactBossPhone] 一一对应。 */\n'
        '    @SerialName("contact_boss_name") val contactBossName: String = "",\n',
        "",
        "OrderDto 收这两个名称",
    ),
    (
        # ⚠️ 2026-09-22 修：锚点原来是 `OutlinedTextField(...)`，而这一页早就改成了共用表单行
        #    （`FormInputRow`）→ 注入变成 [SKIP]，也就是说这条**一直没在验**（永远红的检查＝没有检查）。
        "下单页少了「下单人名称」输入框",
        CREATE_SCREEN,
        '                        label = "下单人名称",\n',
        '                        label = "次要联系人名称",\n',
        "下单页有「下单人名称」输入框",
    ),
    (
        "选了线路也不带出收货人名字（每次都要手打）",
        CREATE_VM,
        "        if (a.receiverName.isNotBlank()) dongjiaName = a.receiverName\n",
        "",
        "收货人名称从选中的线路带出来",
    ),
    (
        "自动填拿会话里的 username 当电话（那可能是人名，打不通）",
        CREATE_VM,
        "prefillOrdererFromSelf(me.fullName.ifBlank { s?.fullName }, me.phone)",
        "prefillOrdererFromSelf(me.fullName.ifBlank { s?.fullName }, s?.username)",
        "自动填没有把会话里的 username 当电话",
    ),
    (
        "卡片上不再显示收货人",
        CARD,
        '                "收货人" to contactWho(order.contactDongjiaName, order.contactDongjiaPhone),\n',
        "",
        "卡片上有「收货人」这一行",
    ),
    (
        "「名字（电话）」又被拼了第二份（卡片与详情会不一致）",
        CARD,
        "internal fun contactWho(name: String?, phone: String?): String? {\n",
        "internal fun contactWho(name: String?, phone: String?): String? {\n"
        "internal fun contactWho(name: String?, phone: String?): String? {\n",
        "只有一份实现",
    ),
    (
        # ⚠️ 2026-09-22 修：锚点原来是 `InfoRow("下单人", who)`，而详情页那一行早就改成
        #    "可点击拨打 + 点击先弹确认"的自绘行 → 注入变成 [SKIP]（同上面那条，一直没在验）。
        "详情页又用回旧词「老板电话」（与下单页/卡片/AI 不一致）",
        DETAIL,
        '                        Text("下单人", style = MaterialTheme.typography.bodyMedium, '
        "modifier = Modifier.weight(1f))\n",
        '                        Text("老板电话", style = MaterialTheme.typography.bodyMedium, '
        "modifier = Modifier.weight(1f))\n",
        "订单详情里没有旧词",
    ),
    (
        "AI 改单的动作里没有这两个名字（模型只能答「改不了」）",
        AI_CATALOG,
        '                AiWriteParam("dongjia_name", "收货人名称", hint = "可选。到现场接货的人叫什么"),\n',
        "",
        "AI 改单的动作有这两个名称参数",
    ),
    (
        "旧库补列那一段被删了（老库升级后这两列不存在，接口直接 500）",
        BOOTSTRAP,
        '        ("orders", "contact_dongjia_name",\n'
        '         "ALTER TABLE orders ADD COLUMN contact_dongjia_name VARCHAR(64) NOT NULL DEFAULT \'\'"),\n',
        "",
        "schema_bootstrap 能给旧库补上 contact_dongjia_name",
    ),
    # ===== 第二轮（2026-09-22）：「下单人」＝这一单的货主 =====
    (
        "⛔ 代理下单**一位货主都没选**时回落成当前登录账号（又变成「派单员下的单」）",
        ORDERER_PREFILL,
        '    val s = shipper ?: return OrdererContact("", "")',
        "    val s = shipper ?: return OrdererContact(ownName.orEmpty().trim(), ownPhone.orEmpty().trim())",
        "绝不回落成当前登录账号",
    ),
    (
        "⛔ 临时货主也编一个电话出来（库里没有他的号 → 编出来只能是别人的）",
        ORDERER_PREFILL,
        '    if (temp.isNotEmpty()) return OrdererContact(temp, "")',
        '    if (temp.isNotEmpty()) return OrdererContact(temp, "13800000000")',
        "电话留空",
    ),
    (
        "判据被判了两份实现（两个入口必然分叉：改一处漏一处）",
        ORDERER_PREFILL,
        "fun ordererContactFor(\n",
        "fun ordererContactFor2(\n",
        "只有一处实现",
    ),
    (
        "代理下单时又把**派单员自己**预填进去（`if (!proxyMode)` 那道门没了）",
        CREATE_VM,
        "            if (!proxyMode) {\n",
        "            if (true) {\n",
        "代理下单**不预填自己**",
    ),
    (
        "换了货主不重算下单人（下单人留着上一位的姓名 + 电话 → 打过去是别人）",
        CREATE_VM,
        "        if (proxyMode) applyOrdererFromShipper(id)\n",
        "",
        "换货主时重算下单人",
    ),
    (
        "名册里查不到时不去单取（用预订单/带参直达进这一页时下单人是空的）",
        CREATE_VM,
        "            val u = runCatching { container.repo.userById(id) }.getOrNull() ?: return@launch\n",
        "            val u = runCatching { container.repo.me() }.getOrNull() ?: return@launch\n",
        "单取一位货主",
    ),
    (
        "异步回包不带校验（这期间换了货主 → 下单人被写成上一位）",
        CREATE_VM,
        "            if (proxyMode && shipperId == id && tempShipperName == null) {\n",
        "            if (true) {\n",
        "异步回包带校验",
    ),
    (
        "后端兜底只在**一栏**空时就补（名字写王老板、电话却是货主账号那个号）",
        API,
        "        if not boss_name and not boss_phone:\n",
        "        if True:\n",
        "两栏都空",
    ),
    (
        "后端**货主自己下单也补**（把「客户端明明填了空」悄悄盖成货主）",
        API,
        "    if target_shipper is not None and target_shipper.id != current.id:\n",
        "    if target_shipper is not None:\n",
        "只有**代理下单**才兜底",
    ),
    (
        "⛔ 把货主自己记成他自己的联系人（每下一次单就长一条「我自己」）",
        CONTACT_SVC,
        "    if own_phone and own_phone.strip() == phone:\n",
        "    if False:\n",
        "不进他自己的联系人名册",
    ),
    (
        "后端用例被删掉（兜底这条路再也没人验）",
        BACKEND_TEST,
        "def test_代理下单只带一栏时不补另一栏(client, users, token_dispatcher):\n",
        "def test_代理下单只带一栏时不补另一栏_v2(client, users, token_dispatcher):\n",
        "用例钉着「两栏都空才补」",
    ),
    (
        "后端用例被改成空跑（`is not None` 等于什么都没验）",
        BACKEND_TEST,
        '    assert only_name["contact_boss_phone"] == ""\n',
        '    assert only_name["contact_boss_phone"] is not None\n',
        "用例真的在断言",
    ),
]


def read_src(p: Path) -> tuple[str, bool]:
    data = p.read_bytes()
    return data.decode("utf-8").replace("\r\n", "\n"), b"\r\n" in data


def write_src(p: Path, text: str, crlf: bool) -> None:
    data = text.replace("\r\n", "\n")
    if crlf:
        data = data.replace("\n", "\r\n")
    p.write_bytes(data.encode("utf-8"))


def run_check() -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    bad = 0
    code, out = run_check()
    if code != 0:
        print(f"❌ 前提不成立：源码完好时这条红线没过\n{out[-1500:]}")
        return 1
    print("✅ 前提：源码完好时这条红线是绿的")

    for label, path, old, new, expect in MUTATIONS:
        src, crlf = read_src(path)
        if src.count(old) != 1:
            print(f"  [SKIP] {label} —— 原文出现 {src.count(old)} 次，无法唯一替换")
            bad += 1
            continue
        write_src(path, src.replace(old, new), crlf)
        try:
            code, out = run_check()
            fails = [ln for ln in out.splitlines() if "[FAIL]" in ln]
            hit = code != 0 and any(expect in ln for ln in fails)
            detail = f"实际红 {len(fails)} 条" + ("" if hit else f"：{[f.strip()[:70] for f in fails[:2]]}")
        finally:
            write_src(path, src, crlf)
        print(f"  [{'OK' if hit else 'MISS'}] {label} → {detail}")
        if not hit:
            bad += 1

    code, out = run_check()
    ok = code == 0
    print("  [OK] 还原后红线全绿" if ok else "  [MISS] 还原后红线没恢复")
    bad += 0 if ok else 1

    total = len(MUTATIONS) + 1
    print()
    if bad:
        print(f"❌ {bad}/{total} 条不成立（红线对它们不敏感）")
        return 1
    print(f"✅ {total}/{total} 全部成立：每条注入都让红线点出了那一条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
