"""反向验证 §31（商品分类名册 / 商品可见白名单 / 常用地点 / 一次性提示 / 选地点都能搜）。

## 为什么这一节也要配反向验证
§31 的判据全是**静态结构断言**，而这类判据最容易变成空转：正则少个转义、
扫错文件、替换串过期 —— 它照样全绿。本仓库栽过 6 次，规矩是**新增红线就要有注入实验**。

这一轮特别容易空转的四条（注入点都选在"旧检查不看的地方"）：
1. **改名级联**：只锚"有没有这个函数"的话，把那条 `UPDATE products` 删掉照样绿 ——
   而后果是"改完名商品全变未分类，且不报错"；
2. **可见白名单**：只在选品页藏起来、接口照收 = 看起来限制了、其实没有。
   所以"列表过滤 / 详情 404 / 下单校验"三处都要能各自变红；
3. **None vs 空集合**：不受限必须用 `None` 表示。改成"返回空集合"的话，
   所有没配过白名单的货主会当场什么都看不到 —— 而代码看起来只是"少了个分支"；
4. **先消费再显示**：顺序反了不会报错，只会在**切页返回时**把提示条重放一次
   （用户报的就是这个）。

用法：`python _tools/qa/_reverse_verify_catalog_and_scope.py`
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import repo_root  # noqa: E402

ROOT = repo_root()
AI_TOOLS = ROOT / "_tools" / "ai"
GUARDRAILS = AI_TOOLS / "_check_ai_guardrails.py"

PCAT_API = ROOT / "backend/app/api/v1/product_categories.py"
PCAT_MODEL = ROOT / "backend/app/models/product_category.py"
PRODUCTS_API = ROOT / "backend/app/api/v1/products.py"
ORDERS_API = ROOT / "backend/app/api/v1/orders.py"
USERS_API = ROOT / "backend/app/api/v1/users.py"
VIS_SCHEMA = ROOT / "backend/app/schemas/product_visibility.py"
USER_MODEL = ROOT / "backend/app/models/user.py"
BOOTSTRAP = ROOT / "backend/app/core/schema_bootstrap.py"
PLACE_SVC = ROOT / "backend/app/services/place_service.py"
PLACES_API = ROOT / "backend/app/api/v1/places.py"
PICKER = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/common/ProductPicker.kt"
COMPONENTS = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/common/Components.kt"
MSG_SCREEN = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/messages/MessagesScreen.kt"
OCS = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/shipper/OrderCreateScreen.kt"
ADDR_SCREEN = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/shipper/AddressScreen.kt"
# ⚠️ 2026-09-20：这个文件原来叫 `WholesalePricingViewModel.kt`，已改名为
#    `PriceMatrixViewModel.kt`（批发商定价现在就是那张价格矩阵）。改名的后果是
#    **这份反向验证直接 FileNotFoundError 崩掉**——脚本读不到文件时必须是"报红"，
#    而它当时是抛异常退出（也算非零），所以 `--deep` 只是把它记成"不达标"。
#    路径跟着改名走：不然这条用例会一直红着，而人要花时间去查"到底哪儿坏了"。
WPVM = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/PriceMatrixViewModel.kt"

SECTION = 31

#: (说明, 目标文件, 替换函数)
CASES: list[tuple[str, Path, object]] = [
    # ------------------------------------------------ ① 分类名册
    (
        "名册不再按 sort_order 排（顺序又变成随机的）",
        PCAT_API,
        lambda s: s.replace(
            "select(ProductCategory).order_by(ProductCategory.sort_order, ProductCategory.id)",
            "select(ProductCategory)",
            1,
        ),
    ),
    (
        "改名不再级联（改完名商品全变未分类，而且不报错）",
        PCAT_API,
        lambda s: s.replace(
            "        moved = db.execute(\n"
            "            # ⚠️ 必须带上 `is_deleted=False` 之外的**全部**行：软删的商品也一起改名，\n"
            "            #    否则恢复那个商品时它挂的是一个已经不存在的分类名（选品页会多出一格）。\n"
            "            Product.__table__.update().where(Product.category == old_name).values(category=body.name)\n"
            "        ).rowcount",
            "        moved = 0",
            1,
        ),
    ),
    (
        "删除分类不再检查「还有几个商品挂着」（悄悄把商品变成未分类）",
        PCAT_API,
        lambda s: s.replace("    if used:", "    if False:", 1),
    ),
    (
        "reorder 不再要求整份（没提到的静默保持原序，两端各错一次）",
        PCAT_API,
        lambda s: s.replace("    if missing:", "    if False:", 1),
    ),
    (
        "新建商品时不再自动把分类补进名册（刚建的分类跑到最后）",
        PRODUCTS_API,
        lambda s: s.replace('    ensure_category(db, body.category or "")', "", 1),
    ),
    (
        "选品页不再用名册顺序（退回按商品数推）",
        PICKER,
        lambda s: s.replace(
            "    ordered.map { it.trim() }.filter { it.isNotEmpty() && it in inRail }.distinct().forEach { out += it }",
            "",
            1,
        ),
    ),
    (
        "名册外的分类被藏掉（等于一个静默的商品过滤器）",
        PICKER,
        lambda s: s.replace(
            "        .filter { it.key != NO_CATEGORY && it.key !in out }",
            "        .filter { it.key != NO_CATEGORY && it.key in ordered }",
            1,
        ),
    ),
    # ------------------------------------------------ ② 可见白名单
    (
        "迁移把老账号回填成 custom（上线那一刻所有货主选品页变空）",
        BOOTSTRAP,
        lambda s: s.replace(
            "ADD COLUMN product_scope VARCHAR(16) NOT NULL DEFAULT 'all'",
            "ADD COLUMN product_scope VARCHAR(16) NOT NULL DEFAULT 'custom'",
            1,
        ),
    ),
    (
        "「不受限」改成返回空集合（默认把所有人挡在外面）",
        VIS_SCHEMA,
        lambda s: s.replace(
            '    if (getattr(user, "product_scope", None) or SCOPE_ALL) != SCOPE_CUSTOM:\n        return None',
            '    if (getattr(user, "product_scope", None) or SCOPE_ALL) != SCOPE_CUSTOM:\n        return set()',
            1,
        ),
    ),
    (
        "可见性对派单员也生效（把自己挡在外面，改错了没人能改回来）",
        VIS_SCHEMA,
        lambda s: s.replace(
            "    return role_key.lower() == UserRole.SHIPPER.value",
            "    return True",
            1,
        ),
    ),
    (
        "商品列表不再按白名单过滤（藏起来的商品照样出现在目录里）",
        PRODUCTS_API,
        lambda s: s.replace(
            "    ids = visible_product_ids(db, current)\n    if ids is not None:",
            "    ids = None\n    if ids is not None:",
            1,
        ),
    ),
    (
        "白名单外的商品详情不再按「不存在」回（403 等于告诉他有个看不到的商品）",
        PRODUCTS_API,
        lambda s: s.replace(
            "    if not product_visible_to(db, current, p.id):\n"
            '        raise HTTPException(status_code=404, detail="未找到对应记录")',
            "    pass",
            1,
        ),
    ),
    (
        "下单不再校验可见性（藏起来的商品照样能塞进单里）",
        ORDERS_API,
        lambda s: s.replace(
            "        if not product_visible_to(db, current, ln.product_id)",
            "        if False",
            1,
        ),
    ),
    (
        "custom 但一个都没勾不再拒绝（用户以为配好了、其实什么都看不到）",
        USERS_API,
        lambda s: s.replace("        if not body.product_ids:", "        if False:", 1),
    ),
    (
        "可见范围不再留痕（授权改动查不到是谁改的）",
        USERS_API,
        # ⚠️ 注入要**真的把那块删掉**，不能只包一层 `if False:` ——
        #    包一层的话 `write_log(` 那几行还在文件里，只锚"存不存在"的断言照样绿
        #    （第一版就是这么注入的，被这次运行抓出来）。
        #    而且"有人把日志那几行删了"本来就是更现实的缺陷形态。
        lambda s: s.replace(
            "    write_log(\n"
            "        db,\n"
            "        operator_id=current.id,\n"
            "        order_id=None,\n"
            "        action=OperationAction.PRODUCT_VISIBILITY_SET,\n"
            "        change_payload={\n"
            '            "user_id": u.id,\n'
            '            "user_name": u.full_name or u.phone,\n'
            '            "scope": out.scope,\n'
            '            "product_ids": out.product_ids,\n'
            '            "product_count": len(out.product_ids),\n'
            "        },\n"
            "    )\n",
            "",
            1,
        ),
    ),
    # ------------------------------------------------ ③ 常用地点
    (
        "阈值改成 1（第一次点就灌进自己的库）",
        PLACE_SVC,
        lambda s: s.replace("AUTO_ADD_AFTER = 2", "AUTO_ADD_AFTER = 1", 1),
    ),
    (
        "改用全库 use_count 当判据（热闹的地点涌进所有人的库）",
        PLACE_SVC,
        lambda s: s.replace(
            "    if row.auto_added or row.use_count < AUTO_ADD_AFTER:",
            "    if row.auto_added or place.use_count < AUTO_ADD_AFTER:",
            1,
        ),
    ),
    (
        "不再限制角色（司机也往 shipper_locations 里写）",
        PLACE_SVC,
        lambda s: s.replace(
            '    if role_key not in ("shipper", "dispatcher"):\n        return row.use_count, False',
            "",
            1,
        ),
    ),
    (
        "自动加库不留痕（用户只能猜是谁加的）",
        PLACES_API,
        lambda s: s.replace(
            "            action=OperationAction.PLACE_AUTO_ADDED,",
            '            action=OperationAction.LEDGER_UPDATE,',
            1,
        ),
    ),
    # ------------------------------------------------ ④ 选地点都能搜
    (
        # 2026-09-20 更新锚点（这次连**注入的形状**一起换）：提示语已经挪出 `placeholder`，
        # 所以"改提示语"不再代表"搜索退回只有共享地点那段"。
        # 真正的缺陷形状是：**本地那两段不再过滤**（只有共享地点段（打后端）能搜）——
        # 用户会很自然地读成"搜不到就是没有这个地点"，然后去新建一条重复的。
        "下单页搜索框退回「只有共享地点那段才有」（本地两段不再过滤）",
        OCS,
        lambda s: s.replace(
            "    val shownAddresses = remember(addresses, kw) {\n"
            "        if (kw.isBlank()) addresses\n"
            "        else addresses.filter {\n"
            "            it.receiverName.contains(kw, true) || it.phone.contains(kw) || it.detailAddress.contains(kw, true)\n"
            "        }\n"
            "    }",
            "    val shownAddresses = remember(addresses, kw) { addresses }",
            1,
        ),
    ),
    (
        "地址与联系人页的搜索框被拿掉",
        ADDR_SCREEN,
        lambda s: s.replace(
            '0 -> "搜线路：收货人 / 电话 / 地址"',
            '0 -> "搜索"',
            1,
        ),
    ),
    # ------------------------------------------------ ⑤ 一次性提示
    (
        "OneShotSnackbar 顺序反过来（先显示再消费 → 切页返回会重放）",
        COMPONENTS,
        lambda s: s.replace(
            "        onConsumed()\n        hostState.showSnackbar(message)",
            "        hostState.showSnackbar(message)\n        onConsumed()",
            1,
        ),
    ),
    (
        "消息页退回旧写法（用户报的那个 bug 复现）",
        MSG_SCREEN,
        lambda s: s.replace(
            "    OneShotSnackbar(snackbar, vm.notice, onConsumed = { vm.notice = null })",
            "    LaunchedEffect(vm.notice) {\n"
            "        vm.notice?.let {\n"
            "            snackbar.showSnackbar(it)\n"
            "            vm.notice = null\n"
            "        }\n"
            "    }",
            1,
        ),
    ),
    (
        "加载错误与动作错误又合并成一个字段（提示条一消费，整页 ErrorView 就没了）",
        WPVM,
        lambda s: s.replace(
            "    var loadError by mutableStateOf<String?>(null)",
            "    val loadError: String? get() = error",
            1,
        ),
    ),
]


def run(path: Path) -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ROOT),
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def section(out: str, n: int) -> str:
    """只取 §n 那一段（段内失败标记是 `[FAIL]`，不是汇总里的 ❌）。"""
    head = f"== {n}."
    if head not in out:
        return ""
    rest = out.split(head, 1)[1]
    return rest.split("\n" + "=" * 60, 1)[0]


def main() -> int:
    fails: list[str] = []
    code, out = run(GUARDRAILS)
    if code != 0:
        print(f"❌ 前提不成立：源码完好时红线就没过\n{out[-1500:]}")
        return 1
    if not section(out, SECTION):
        print(f"❌ 前提不成立：输出里找不到 §{SECTION} 这一段")
        return 1
    print(f"✅ 前提：源码完好时红线是绿的（§{SECTION} 在）")

    for label, path, mutate in CASES:
        original = path.read_text(encoding="utf-8")
        mutated = mutate(original)
        if mutated == original:
            fails.append(f"{label}：注入没生效（替换串过期了，请更新本脚本）")
            continue
        try:
            path.write_text(mutated, encoding="utf-8", newline="")
            code2, out2 = run(GUARDRAILS)
            red = code2 != 0 and "[FAIL]" in section(out2, SECTION)
        finally:
            path.write_text(original, encoding="utf-8", newline="")
        if red:
            print(f"✅ 注入「{label}」→ 报红")
        else:
            fails.append(f"{label}：注入之后没有报红 —— 这条判据是空转的")

    if fails:
        print("\n❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"\n✅ §{SECTION} 共 {len(CASES)} 条注入全部证明会红。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
