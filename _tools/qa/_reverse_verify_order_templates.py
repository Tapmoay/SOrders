"""反向验证：把「预订单」那条红线逐条弄坏，看它**真的会红**。

## 为什么这块必须反向验证
预订单坏掉的方式**全部不报错、不崩**：
· 预设单悄悄变成"第二套下单路径" → 订单状态核对/库存/账本口径多出第二份实现，**当天的账就错了**；
· 行里存了单价 → 几个月后按旧价下单，界面上一点异样都没有；
· 把"没填运费"当成 0 → 每张预设单都成了免运费单（一键下单时钱就少收了）；
· 预填不整份替换（改成追加）→ 上一次没提交干净的行混进来 = **多订一样货**；
· 预填价格自己写一遍（不走 `priceFor`）→ 批发商的专属价被跳过，报价串号；
· **价还在路上就把行价算定了**（预填不等取数回来）→ 谈好的专属价被跳过，按默认价下单（2026-09-22 真机错价）；
· **规则到齐后不重算已填好的行** / **取数失败被当成"这个货主没有专属价"** / **没拿到价也照样提交**
  → 三件都是"报了错价而**两边都不报错**"，事后无从发现；
· **报价依据那句话不画在界面上**（或不再看专属价规则）→ 用户没有任何办法看出这次走的是默认价还是谈好的价；
· **一次性提示只剩地址抽屉里那一个渲染点** → "已按预设单填好""某件商品已不在商品库"这些话**等于没有反馈**；
· 常用度记在"点开"而不是"下单成功" → 列表排序变成"谁点开过"；
· 撤回按钮没了 → 删了就再也找不回来（用户定的硬规矩是"手边要有撤销入口"）。

用法：python _tools/qa/_reverse_verify_order_templates.py    # 全部报红 → 退出码 0
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_order_templates.py"

ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
API = ROOT / "backend/app/api/v1/order_templates.py"
SCHEMA = ROOT / "backend/app/schemas/order_template.py"
TEST = ROOT / "backend/tests/test_order_templates.py"
SCREEN = ANDROID / "ui/dispatcher/OrderTemplatesScreen.kt"
CREATE_VM = ANDROID / "ui/shipper/OrderCreateViewModel.kt"
CREATE_SCREEN = ANDROID / "ui/shipper/OrderCreateScreen.kt"
NAV = ANDROID / "ui/nav/NavGraph.kt"
MODULES = ANDROID / "ui/nav/Modules.kt"
AI_RES = ANDROID / "ai/AiResources.kt"
COVERAGE = ROOT / "_tools/ai/_app_feature_coverage.py"
DESIGN = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"

# (说明, 文件, 原文, 替换成, 期望变红的检查名关键词)
MUTATIONS = [
    (
        "「没填运费」被当成 0（每张预设单都成了免运费单 —— 一键下单时钱就少收了）",
        API,
        "    if not text:\n        return None",
        '    if not text:\n        return q2(Decimal("0"))',
        "空串/None 一律当「不预设」",
    ),
    (
        "删端点换成一个更宽的权限点（谁都删得掉预设单）",
        API,
        '    operator: User = Depends(require_permission(Permission.ORDER_EDIT)),\n) -> None:',
        "    operator: User = Depends(require_permission(Permission.ORDER_CREATE)),\n) -> None:",
        "六个端点全都守在 ORDER_EDIT 上",
    ),
    (
        "列表不再按常用度排（用完的预设单永远排在后面）",
        API,
        "            usage_service.with_popularity(",
        "            select(",
        "列表按常用度排序",
    ),
    (
        "回收站里的预设单也能改（用户以为改的是「现在在用的那一张」）",
        API,
        '    ensure_alive(tpl, "预设单", "POST /order-templates/{id}/restore")\n\n    before = {',
        "    before = {",
        "回收站里的预设单改不了",
    ),
    (
        "没有商品的行被静默丢掉（少一行货＝下单时少订一样，两边都不报错）",
        API,
        'raise HTTPException(status_code=400, detail=f"第 {i} 行没有选商品")',
        "continue",
        "没有商品的行直接拒绝",
    ),
    (
        "行里加回单价（价格会变 → 几个月后按旧价下单）",
        SCHEMA,
        "class OrderTemplateLine(BaseModel):\n    \"\"\"预设单里的一行货：**商品编号 + 数量**（+ 两个显示用快照）。\"\"\"\n",
        "class OrderTemplateLine(BaseModel):\n    price: str = \"0\"\n",
        "行里**没有单价**",
    ),
    (
        "回归测试被削弱（部分更新不再核对商品行有没有被动过）",
        TEST,
        'assert len(got["lines"]) == 2, "只改名不该把预设的商品行清掉"',
        "assert True",
        "部分更新不覆盖没提到的键",
    ),
    (
        "这一页自己去建单（下单多出第二条路：状态核对/库存/账本口径抄第二遍）",
        SCREEN,
        "        val t = pendingDelete ?: return\n        pendingDelete = null",
        "        val t = pendingDelete ?: return\n        container.repo.createOrder(\n        pendingDelete = null",
        "这一页**不许**出现建单调用",
    ),
    (
        "删完不给「撤回」（删了就再也找不回来 —— 用户定的硬规矩）",
        SCREEN,
        '            actionLabel = "撤回",',
        '            actionLabel = "知道了",',
        "删完给「撤回」",
    ),
    (
        "预填改成追加（上一次没提交干净的行混进来 = 多订一样货）",
        CREATE_VM,
        "                val missing = ArrayList<String>()\n                lines.clear()",
        "                val missing = ArrayList<String>()",
        "商品行**整份替换**",
    ),
    (
        "预填价格自己写一遍（不走 priceFor → 批发商的专属价被跳过）",
        CREATE_VM,
        'price = p?.let { priceFor(it) } ?: "",',
        'price = p?.defaultUnitPrice ?: "",',
        "单价走唯一那份口径",
    ),
    (
        "预填**不等专属价到齐**就算行价（专属价还在路上 → 行价按默认价算定，谈好的价被跳过）",
        CREATE_VM,
        "                awaitPriceRules()",
        "",
        "预填**先等这个货主的专属价到齐**再算行价",
    ),
    (
        "报价依据在预填横幅里又写了一遍（同屏出现两句互相打架的价：横幅说默认价、明细说专属价）",
        CREATE_VM,
        '                    append("已按预设单「").append(t.name).append("」填好商品与数量，请核对后再提交")',
        '                    append("已按预设单「").append(t.name).append("」填好商品与数量，请核对后再提交")'
        '.append(priceBasisText())',
        "预填横幅里**不许**再写一遍报价依据",
    ),
    (
        "报价依据不再看专属价规则（一律说「按商品默认售价」＝这句话就废了）",
        CREATE_VM,
        "        val special = lines.count { ln -> ln.productId?.let { priceRules[it] != null } == true }",
        "        val special = 0",
        "它真的去看了专属价规则",
    ),
    (
        "顶部横幅被删（提示又变成只有地址抽屉里才画 = 用户看不见）",
        CREATE_SCREEN,
        "        vm.toast?.let { msg ->",
        "        null?.let { msg ->",
        "一次性提示有",
    ),
    (
        "规则到齐后**不重算已有的行**（先挑商品、后换货主 → 行上留着上一个货主的价）",
        CREATE_VM,
        "        priceRules = loaded\n        priceRulesShipper = sid\n        repriceFromRules()",
        "        priceRules = loaded\n        priceRulesShipper = sid",
        "落完规则就**重算已有的行**",
    ),
    (
        "取数失败被当成「这个货主没有专属价」（＝按默认价把单发出去，谈好价的批发商被多收钱）",
        CREATE_VM,
        "    } catch (_: Exception) {\n"
        "        loadingProducts = false   // 失败也要收尾，别让界面永远停在\"加载中\"\n"
        "        null\n"
        "    }",
        "    } catch (_: Exception) {\n"
        "        loadingProducts = false   // 失败也要收尾，别让界面永远停在\"加载中\"\n"
        "        emptyMap()\n"
        "    }",
        "失败**不许**退化成空 map",
    ),
    (
        "提交那道报价闸门被删（还没拿到价也照发：默认价成了实际成交价）",
        CREATE_VM,
        "                        val subject = shipperId ?: myShipperId ?: s?.userId\n"
        "                        if (subject != null && priceRulesShipper != subject) {",
        "                        val subject = shipperId ?: myShipperId ?: s?.userId\n"
        "                        if (false) {",
        "提交那道**报价闸门**",
    ),
    (
        "没有价的那一行也放出去（商品已不在库，后端收到空单价 → 用户看到一个看不懂的 422）",
        CREATE_VM,
        '            noPrice != null -> error = "「${noPrice.name}」没有价格'
        '（这件商品已不在商品库），先删掉这一行再提交"\n',
        "",
        "没有价的那一行**挡住**",
    ),
    (
        "常用度记在别的地方（列表会按「谁点开过」排序）",
        CREATE_VM,
        "runCatching { container.repo.useOrderTemplate(tid) }",
        "runCatching { container.repo.orderTemplates() }",
        "常用度记在**下单成功之后**",
    ),
    (
        "「用这张下单」不再带参（点了只会打开一张空下单页）",
        NAV,
        'Routes.DISPATCH_ORDER_CREATE + "?template=" + t.id',
        "Routes.DISPATCH_ORDER_CREATE",
        "「用这张下单」是**带参跳下单页**",
    ),
    (
        "工作台那一格被删掉（用户从界面上再也找不到预订单）",
        MODULES,
        'ModuleEntry("预订单", Routes.DISPATCH_ORDER_TEMPLATES, Icons.Default.BookmarkAdded, color = 0xFF3949ABL),',
        "",
        "那一格存在且指向它自己那一页",
    ),
    (
        "撤回不再挂到资源表上（删了之后撤回按钮点下去报「没有执行入口」）",
        AI_RES,
        "            paired(\n                AiWrites.ORDER_TEMPLATE_RESTORE,",
        "            paired(\n                AiWrites.ORDER_TEMPLATE_UPDATE,",
        "撤回按资源表声明",
    ),
    (
        "读能力没人认领（能力做出来了、用户在界面上看不到它）",
        COVERAGE,
        # ⚠️ 锚点跟着 `_app_feature_coverage.py` 里的写法走：2026-09-22 那一格改成多行之后
        #    （多了「预订单分类」这条读能力），旧的一行式锚点直接 SKIP —— 反向验证没跑起来。
        '        ["预订单", "预订单分类"],',
        "        [],",
        "读能力被 App 模块认领",
    ),
    (
        "设计规范里那条规矩被删（下一个人不知道「只是预填模板」这条界线）",
        DESIGN,
        "`_tools/qa/_check_order_templates.py`（含反向验证；后端那一半在 `api/v1/order_templates.py`）",
        "（判据脚本名待补）",
        "设计规范里写了预订单那一条规矩",
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


def verdict(expect: str) -> tuple[bool, str]:
    code, out = run_check()
    fails = [ln for ln in out.splitlines() if "[FAIL]" in ln]
    hit = code != 0 and any(expect in ln for ln in fails)
    return hit, f"实际红 {len(fails)} 条" + ("" if hit else f"：{[f.strip()[:70] for f in fails[:2]]}")


def main() -> int:
    bad = 0
    code, out = run_check()
    if code != 0:
        print(f"❌ 前提不成立：源码完好时这条红线没过\n{out[-1200:]}")
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
            hit, detail = verdict(expect)
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
