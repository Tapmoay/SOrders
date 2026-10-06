# -*- coding: utf-8 -*-
r"""勾选商品零件（CHG-0062）的反向验证：一条红线要能被"真的破坏一次"证明它在检查。

每条注入只改一处，跑一遍 _check_product_check_list.py，要求它报红、而且报红的就是这条红线；
跑完按**字节**把被碰过的文件还原，再逐字节核对一遍。
锚点一律不写行首缩进：注入结果不需要能编译，只要判据变红。

被碰的文件不只有零件自己：两个调用方、分类栏的出处（ProductPicker.kt）、
以及账号管理页那侧的委托串（_check_users_form.py）都在注入范围里 ——
"共用零件"这件事只有跨文件才证得动。
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

try:  # PowerShell 重定向时 stdout 会退回 GBK，中文与 ✅ 都编不出去
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_product_check_list.py"

PART = "android/app/src/main/java/com/tapmoay/sorders/ui/common/ProductCheckList.kt"
BATCH = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ProductBatchScreen.kt"
USERS = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/UsersManageScreen.kt"
PICKER = "android/app/src/main/java/com/tapmoay/sorders/ui/common/ProductPicker.kt"
USERS_CHECK = "_tools/qa/_check_users_form.py"

NL = chr(10)
Q = chr(34)


def gsub(s: str, pat: str, rep: str) -> str:
    r"""按正则换一处（锚点里用 \s* 兜住缩进，不数空格）。"""
    return re.sub(pat, rep, s, count=1)


CASES: list[tuple[str, str, object, str]] = [
    # ── 0. 反空转 ＋ 复用 ─────────────────────────────────────────────────
    ("零件被掏空（定义改了名）",
     PART,
     lambda s: s.replace("internal fun ProductCheckList(", "internal fun ProductCheckListOld(", 1),
     "零件在这里定义"),
    ("零件自己画了一份商品行（ProductLine 定义搬了进来）",
     PART,
     lambda s: s.replace("internal fun ProductCheckList(",
                         "private fun ProductLine() {}" + NL + "internal fun ProductCheckList(", 1),
     "行外观不自己画"),
    ("零件自己画缩略图（ProductThumb 换成别的）",
     PART,
     lambda s: s.replace("ProductThumb(imageUrl = p.imageUrl, nameColor = p.nameColor, size = 40.dp)",
                         "Box()", 1),
     "行外观不自己画"),
    ("零件自己画了一条分类栏（CategoryRail 定义搬了进来）",
     PART,
     lambda s: s.replace("internal fun ProductCheckList(",
                         "private fun CategoryRail() {}" + NL + "internal fun ProductCheckList(", 1),
     "分类栏不自己画"),
    ("分类栏的下家没了（ProductPicker 里的 CategoryRail 改了名）",
     PICKER,
     lambda s: s.replace("fun CategoryRail(", "fun CategoryRailOld(", 1),
     "分类栏不自己画"),

    # ── 1. 搜索：受控 ＋ 零件里过滤 ＋ 能清掉 ─────────────────────────────
    ("搜索框变成本地状态（value 固定空串）",
     PART,
     lambda s: s.replace("value = keyword,", "value = " + Q + Q + ",", 1),
     "搜索框是受控的"),
    ("搜索框不再回传（onValueChange 断线）",
     PART,
     lambda s: s.replace("onValueChange = onKeywordChange,", "onValueChange = {},", 1),
     "搜索框是受控的"),
    ("零件自己 remember 了一份搜索词",
     PART,
     lambda s: s.replace("val kw = keyword.trim()", "var keyword = " + Q + Q + NL + "        val kw = keyword.trim()", 1),
     "搜索词不是零件自己记的"),
    ("过滤挪回调用方（零件里不再按名称滤）",
     PART,
     lambda s: s.replace("it.name.contains(kw, ignoreCase = true)", "true", 1),
     "过滤在零件里做"),
    ("「清空搜索」的 × 没了（点了不通知外面）",
     PART,
     lambda s: s.replace("IconButton(onClick = { onKeywordChange(" + Q + Q + ") })", "IconButton(onClick = {})", 1),
     "清空搜索"),
    ("两种空因混成一句（搜不到也说「暂无商品」）",
     PART,
     lambda s: s.replace(Q + "没有名称含「" + Q + " + kw + " + Q + "」的商品" + Q,
                         Q + "暂无商品" + Q, 1),
     "空态分两种"),

    # ── 2. 左分类栏 ＋ 三态分类头 ─────────────────────────────────────────
    ("左分类栏不再跟着选中那档走",
     PART,
     lambda s: s.replace("selected = category,", "selected = ALL_CATEGORY,", 1),
     "左分类栏在"),
    ("分类顺序不再听调用方的（categoryOrder 丢了）",
     PART,
     lambda s: s.replace("categoryTabs(products, categoryOrder)", "categoryTabs(products)", 1),
     "分类顺序听调用方的"),
    ("选中那一档没了就停在空清单上（不回「全部」）",
     PART,
     lambda s: s.replace("if (category !in cats) category = ALL_CATEGORY", "if (false) category = ALL_CATEGORY", 1),
     "选中那一档没了就回「全部」"),
    ("分类头退回两态（勾了一半看不出来）",
     PART,
     lambda s: s.replace("else -> ToggleableState.Indeterminate", "else -> ToggleableState.Off", 1),
     "分类头是三态"),
    ("分类头的状态不再从 checkedIds 算",
     PART,
     lambda s: s.replace("state = triStateOf(visible, checkedIds)", "state = ToggleableState.Off", 1),
     "分类头是三态"),
    ("点分类头时 targetOn 不再明着给",
     PART,
     lambda s: s.replace("onToggleCategory(category, state != ToggleableState.On, visible.map { it.id })",
                         "onToggleCategory(category, state != ToggleableState.Off, visible.map { it.id })", 1),
     "半选时点一下朝「全勾」走"),
    ("筛选出来的那批被当成了一整个分类（文案只剩一档）",
     PART,
     lambda s: s.replace(Q + "全选这一类（" + Q + " + visible.size + " + Q + "）" + Q,
                         Q + "全选这一类" + Q, 1),
     "分类头文案两档分开"),

    # ── 3. 勾选行 ────────────────────────────────────────────────────────
    ("商品行不再反映勾选状态（勾的都是空的）",
     PART,
     lambda s: s.replace("val on = p.id in checkedIds", "val on = false", 1),
     "商品行还是可勾的"),
    ("Checkbox 点了不通告外面",
     PART,
     lambda s: s.replace("onCheckedChange = { onToggleProduct(p.id) },", "onCheckedChange = {},", 1),
     "商品行还是可勾的"),
    ("只剩小方框能点（整行不可点）",
     PART,
     lambda s: s.replace(".clickable(enabled = !locked) { onToggleProduct(p.id) }",
                         ".clickable { onToggleProduct(p.id) }", 1),
     "整行也能点"),
    ("禁勾只禁了一半（Checkbox 还能勾）",
     PART,
     lambda s: s.replace("enabled = !locked,", "enabled = true,", 1),
     "禁勾的行真禁掉"),
    ("下架商品在清单里看不出（徽标没了）",
     PART,
     lambda s: s.replace("badge = if (p.isActive) null else ({ ProductSoldOutBadge() }),", "badge = null,", 1),
     "下架商品在清单里也看得出"),
    ("行的事实不再走 productFacts()",
     PART,
     lambda s: s.replace("facts = productFacts(p.defaultUnitPrice, p.unit, p.stock, p.lowStockAlert),",
                         "facts = " + Q + Q + ",", 1),
     "行的事实走 productFacts()"),

    # ── 4. 自己滚 ＋ 不许藏行 ────────────────────────────────────────────
    ("清单不再自己滚（LazyColumn 换回 Column）",
     PART,
     lambda s: s.replace("LazyColumn(", "Column(", 1),
     "清单自己滚"),
    ("零件套了一层 verticalScroll（塞进可滚容器会量成无限高）",
     PART,
     lambda s: s.replace("Column(modifier) {",
                         "Column(modifier.verticalScroll(rememberScrollState())) {", 1),
     "不套外层 verticalScroll"),
    ("又多了一个筛子（按「还上架」收窄清单）",
     PART,
     lambda s: s.replace("it.name.contains(kw, ignoreCase = true) }",
                         "it.name.contains(kw, ignoreCase = true) }.filter { it.isActive }", 1),
     "清单只按「分类 ＋ 搜索词」收窄"),
    ("锁定的行被藏起来了（不是禁勾，是看不见）",
     PART,
     lambda s: s.replace("items(visible, key = { it.id })",
                         "items(visible.filter { !(rowLocked?.invoke(it) == true) }, key = { it.id })", 1),
     "锁定只进「禁勾」"),
    ("备注画丢了（rowNote 的颜色换了）",
     PART,
     lambda s: s.replace("color = MaterialTheme.colorScheme.onSurfaceVariant,",
                         "color = MaterialTheme.colorScheme.error,", 1),
     "备注画在行下面"),
    ("出错时不能重试（onRetry 断了）",
     PART,
     lambda s: s.replace("ErrorView(error, onRetry = onRetry)", "ErrorView(error)", 1),
     "载入中 / 出错 / 空三种状态都有出口"),

    # ── 5. 两个调用方都走这一份 ───────────────────────────────────────────
    ("批量操作页不再用这个零件（自己拼了一套）",
     BATCH,
     lambda s: s.replace("ProductCheckList(", "BatchPickList(", 1),
     "批量操作页调用它"),
    ("批量操作页调了两遍（谁也不知道哪一份算）",
     BATCH,
     lambda s: s.replace("ProductCheckList(", "ProductCheckList(" + NL + "    ProductCheckList(", 1),
     "批量操作页调用它"),
    ("商品可见范围第二层不再用这个零件（自己拼了一套）",
     USERS,
     lambda s: s.replace("ProductCheckList(", "VisibilityPickList(", 1),
     "商品可见范围第二层调用它"),
    ("可见范围那层没把「勾中的是谁」交给零件（勾了等于没勾）",
     USERS,
     lambda s: s.replace("checkedIds = seen,", "checkedIds = emptySet(),", 1),
     "勾中的是谁"),
    ("批量操作页自己又拼了个三态头",
     BATCH,
     lambda s: s.replace("ProductCheckList(",
                         "TriStateCheckbox()" + NL + "    ProductCheckList(", 1),
     "不再拼三态头"),
    ("可见范围那层自己又拼了个三态头",
     USERS,
     lambda s: s.replace("ProductCheckList(",
                         "TriStateCheckbox()" + NL + "    ProductCheckList(", 1),
     "不再拼三态头"),

    # ── 6. 接线 ＋ KDoc 里的「为什么」 ────────────────────────────────────
    ("账号管理页那侧不再委托零件判据（清单又成了没人盯的地方）",
     USERS_CHECK,
     lambda s: s.replace('PART_REVERSE = ROOT / "_tools/qa/_reverse_verify_product_check_list.py"',
                         'PART_REVERSE = ROOT / "_tools/qa/_reverse_verify_product_check_listOLD.py"', 1),
     "把清单侧委托给了本脚本"),
    ("KDoc 里的「为什么」删了（下一个人会把两边又合成一份）",
     PART,
     lambda s: s.replace("所以差别全部落在回调里", "所以差别在这里", 1),
     "KDoc 留着「为什么」"),
    ("KDoc 不再引用户原话",
     PART,
     lambda s: s.replace("能复用就复用", "尽量共用", 1),
     "KDoc 引着用户原话"),
]


def run_check() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    fails: list[str] = []
    code, out = run_check()
    if code != 0:
        print("❌ 前提不成立：源码完好时这条红线就没过")
        print(out[-1500:])
        return 1
    print("✅ 前提：源码完好时红线是绿的")

    touched = sorted({rel for _l, rel, _m, _e in CASES})
    originals = {rel: (ROOT / rel).read_bytes() for rel in touched}

    for label, rel, mutate, expect in CASES:
        path = ROOT / rel
        original_bytes = originals[rel]
        crlf = b"\r\n" in original_bytes
        plain = original_bytes.decode("utf-8").replace("\r\n", NL)
        mutated = mutate(plain)  # type: ignore[operator]
        if mutated == plain:
            fails.append(label + "：注入没生效（锚点变了，请更新本脚本）")
            print("  [SKIP] " + label)
            continue
        try:
            out_txt = mutated.replace("\r\n", NL)
            if crlf:
                out_txt = out_txt.replace(NL, "\r\n")
            path.write_bytes(out_txt.encode("utf-8"))
            code, out = run_check()
        finally:
            path.write_bytes(original_bytes)
        hit = code != 0 and (not expect or expect in out)
        if hit:
            print("  [OK] " + label + " → 报红")
        else:
            fails.append(label + f"：注入之后没有按预期报红（退出码 {code}，期望关键词「{expect}」）")
            print("  [MISS] " + label + " → 仍然全绿")

    dirty = [rel for rel in touched if (ROOT / rel).read_bytes() != originals[rel]]
    if dirty:
        fails.append("跑完没逐字节还原：" + "、".join(dirty))
        for rel in dirty:
            (ROOT / rel).write_bytes(originals[rel])
        print("⚠️  已强制还原：" + "、".join(dirty))
    else:
        print(f"✅ 还原检查：{len(touched)} 个被碰过的文件与运行前逐字节一致")

    print()
    if fails:
        print("❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"✅ {len(CASES)} 条注入都证明这条红线真的在检查。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
