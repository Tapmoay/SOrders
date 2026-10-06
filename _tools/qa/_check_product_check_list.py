#!/usr/bin/env python
"""勾选商品零件（ui/common/ProductCheckList.kt）的机器判据 —— CHG-0062。

盯住六件事：

1. 它真是**共用零件**，不是某一页的私有实现：行外观走 ProductCardKit（ProductLine / ProductThumb）、
   分类栏走 ProductPicker（CategoryRail / categoryTabs），自己一份都不画。
2. 搜索是**受控**的（keyword / onKeywordChange 从调用方来）、过滤在零件里做、有词能一键清掉，
   空态还分「没搜到」与「这一类下暂无商品」两种。
3. 分类头是**三态**（全选 / 半选 / 未选，状态从 checkedIds 算出来），点它必须带 targetOn ——
   半选时「取反」没有定义；选中那一档没了要回「全部」，不许停在空清单上。
4. 勾选行：勾的是 checkedIds、整行也能点、禁勾（rowLocked）真的禁掉、下架有徽标、
   行的事实走 productFacts()。
5. 清单**自己滚**（LazyColumn.fillMaxSize），不许套外层 verticalScroll（LazyColumn 塞进可滚容器
   会被量成无限高、直接崩）；锁定与备注都不许把行藏掉。
6. 两个调用方（批量操作页 / 商品可见范围第二层）**都走这一份**，谁都不许在页面里再拼一套。

为什么这些必须由机器盯着：它们全是"顺手改一下"就散的形态 —— 把 LazyColumn 换成 Column、
把三态退回两态、点分类头写成取反、把锁定的行 filter 掉、把可见范围那层也自己拼一遍……
每一处都能编译、都跑得起来，只在「用户点了一下没反应」「列表滚不动」这种真机症状里才现形。

R4-BOUNDARY-JUSTIFICATION: 这条判据不下沉到任何一层边界。被查的全是画法与交互形态
（谁画行、三态还是两态、有没有自己的滚动容器、禁勾是不是靠藏行），后端契约、领域类型、
权限模型里都没有它们的位置 —— 零件根本不知道"可见范围"这三个字（两个调用方的差别全在回调里）。

用法：python _tools/qa/_check_product_check_list.py  （--list 打一份人读清单）
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _check_hints import Checker, read, strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "tapmoay" / "sorders"
PART = AND / "ui" / "common" / "ProductCheckList.kt"
BATCH = AND / "ui" / "dispatcher" / "ProductBatchScreen.kt"
USERS = AND / "ui" / "dispatcher" / "UsersManageScreen.kt"
CARD_KIT = AND / "ui" / "common" / "ProductCardKit.kt"
PICKER = AND / "ui" / "common" / "ProductPicker.kt"
REVERSE = ROOT / "_tools" / "qa" / "_reverse_verify_product_check_list.py"
USERS_CHECK = ROOT / "_tools" / "qa" / "_check_users_form.py"
MIN_CHARS = 5000


def calls(src: str, name: str) -> int:
    """数调用点（`fun name(` 定义不算）—— 判"是不是真被用上了"。"""
    return len(re.findall(r"(?<!fun )" + re.escape(name) + r"\(", src))


def main() -> int:
    c = Checker()
    raw = read(PART)
    part = strip_comments(raw)
    batch = strip_comments(read(BATCH))
    users = strip_comments(read(USERS))

    # ── 0. 反空转 + 复用（它是零件，不是某一页的私有实现）──────────────────
    c.section("0. 反空转 + 复用：行与分类栏都不许自己画一份")
    c.ok(f"勾选零件去掉注释后 {len(part)} 字符（下限 {MIN_CHARS}）",
         len(part) >= MIN_CHARS, f"零件被掏空 / 路径变了？实测 {len(part)} 字符")
    c.ok("零件在这里定义（ui/common/ProductCheckList.kt，恰好一处）",
         part.count("internal fun ProductCheckList(") == 1,
         "定义搬走了 / 被复制成了第二份")
    c.ok("行外观不自己画（ProductLine / ProductThumb 来自 ui/common/ProductCardKit.kt）",
         "ProductLine(" in part and "ProductThumb(" in part
         and "fun ProductLine(" not in part and "fun ProductThumb(" not in part
         and "fun ProductLine(" in read(CARD_KIT),
         "自己画行 = 全库又有了第二种商品行")
    c.ok("分类栏不自己画（CategoryRail / categoryTabs 都定义在 ui/common/ProductPicker.kt）",
         "CategoryRail(" in part and "categoryTabs(" in part
         and "fun CategoryRail(" not in part
         and "fun CategoryRail(" in read(PICKER) and "fun categoryTabs(" in read(PICKER),
         "自己画一条分类栏 = 同一个东西又有了第二份")

    # ── 1. 搜索：受控 + 本零件过滤 + 能清掉 ───────────────────────────────
    c.section("1. 搜索：受控（词从外面来）+ 零件里过滤 + 一键清掉")
    c.ok("搜索框是受控的（value = keyword / onValueChange = onKeywordChange 都从外面来）",
         "OutlinedTextField(" in part and "value = keyword," in part
         and "onValueChange = onKeywordChange," in part,
         "零件自己 remember 一份 = 上一层再进来词被清掉（可见范围第二层要留着它）")
    c.ok("搜索词不是零件自己记的（没有本地 var keyword）",
         "var keyword" not in part)
    c.ok("过滤在零件里做（按名称包含、忽略大小写，不是把筛选丢给调用方）",
         "val kw = keyword.trim()" in part
         and "it.name.contains(kw, ignoreCase = true)" in part)
    c.ok("有词时给一个「清空搜索」的 ×（点它走 onKeywordChange）",
         'IconButton(onClick = { onKeywordChange("") })' in part
         and 'contentDescription = "清空搜索"' in part)
    c.ok("空态分两种（「没搜到」与「这一类下暂无商品」—— 别让人以为商品没了）",
         '没有名称含「' in part and "下暂无商品" in part,
         "两种空因混成一句，用户会以为商品被删了")

    # ── 2. 左分类栏 + 三态分类头 ──────────────────────────────────────────
    c.section("2. 左分类栏 ＋ 三态分类头（半选不许被当成没选）")
    c.ok("左分类栏在（CategoryRail，宽度 railWidth、选中那档来自 category）",
         "CategoryRail(" in part and "selected = category," in part
         and "onSelect = { category = it }," in part)
    c.ok("分类顺序听调用方的（categoryOrder 传进 categoryTabs）",
         "categoryTabs(products, categoryOrder)" in part)
    c.ok("选中那一档没了就回「全部」（改名 / 删类之后不许停在空清单上）",
         "LaunchedEffect(cats) { if (category !in cats) category = ALL_CATEGORY }" in part)
    c.ok("分类头是三态（全选 / 一个没勾 / 勾了一半，状态从 checkedIds 算）",
         "state = triStateOf(visible, checkedIds)" in part
         and "private fun triStateOf(visible: List<ProductDto>, checkedIds: Set<Long>): ToggleableState"
             in part
         and all(v in part for v in ("ToggleableState.Off", "ToggleableState.On",
                                     "ToggleableState.Indeterminate")),
         "退回两态 = 勾了一半看不出来")
    c.ok("半选时点一下朝「全勾」走（targetOn 明着传 —— 三态里没有「取反」）",
         "onClick = { onToggleCategory(category, state != ToggleableState.On, visible.map { it.id }) }"
         in part)
    c.ok("分类头文案两档分开（全选这一类（N） / 全选筛选出的 N 个）",
         '"全选这一类（" + visible.size + "）"' in part
         and '"全选筛选出的 " + visible.size + " 个"' in part,
         "筛选出来的那批被当成了一整个分类")

    # ── 3. 勾选行 ────────────────────────────────────────────────────────
    c.section("3. 勾选行：可勾 / 整行可点 / 禁勾真的禁 / 下架有徽标")
    c.ok("商品行还是可勾的 Checkbox（勾中的是 checkedIds 里的 id）",
         "val on = p.id in checkedIds" in part and "checked = on," in part
         and "onCheckedChange = { onToggleProduct(p.id) }," in part)
    c.ok("整行也能点（不只点那小方框）",
         ".clickable(enabled = !locked) { onToggleProduct(p.id) }" in part)
    c.ok("禁勾的行真禁掉（整行与 Checkbox 都看 !locked）",
         "val locked = rowLocked?.invoke(p) == true" in part
         and ".clickable(enabled = !locked)" in part and "enabled = !locked," in part,
         "禁一半 = 用户点一下没反应，却不知道为什么不反应")
    c.ok("下架商品在清单里也看得出（ProductSoldOutBadge）",
         "badge = if (p.isActive) null else ({ ProductSoldOutBadge() })," in part)
    c.ok("行的事实走 productFacts()（售价 / 单位 / 库存同一套算法）",
         "facts = productFacts(p.defaultUnitPrice, p.unit, p.stock, p.lowStockAlert)," in part)

    # ── 4. 自己滚 + 不许藏行 ──────────────────────────────────────────────
    c.section("4. 自己滚、不许藏行")
    c.ok("清单自己滚（LazyColumn ＋ fillMaxSize，占满剩下的高度）",
         "LazyColumn(" in part and "Modifier.fillMaxSize()," in part)
    c.ok("零件不套外层 verticalScroll（塞进可滚容器会量成无限高、直接崩）",
         "verticalScroll(" not in part,
         "这一条正是当年把可见范围摊在抽屉里时崩掉的原因")
    c.ok("清单只按「分类 ＋ 搜索词」收窄（锁定与备注都不许把行藏掉）",
         part.count(".filter {") == 2
         and "categoryOf(it) == category" in part
         and "it.name.contains(kw, ignoreCase = true)" in part,
         "多一个 .filter 就是把某些行藏起来了")
    c.ok("锁定只进「禁勾」、不进筛子（items 画的是 visible，不是 visible.filter）",
         "items(visible, key = { it.id })" in part,
         "藏起来的商品 = 用户以为它不存在，想勾回来都找不到")
    c.ok("备注画在行下面（rowNote，不是替换掉行）",
         "rowNote?.invoke(p)?.let { note ->" in part
         and "color = MaterialTheme.colorScheme.onSurfaceVariant," in part)
    c.ok("载入中 / 出错 / 空三种状态都有出口（LoadingBox / ErrorView / EmptyView）",
         all(v in part for v in ("LoadingBox()", "ErrorView(error, onRetry = onRetry)",
                                 "EmptyView(emptyText)")))

    # ── 5. 两个调用方都走这一份 ───────────────────────────────────────────
    c.section("5. 两个调用方都走这一份（谁也不许再拼一套）")
    c.ok(f"批量操作页调用它（实际 {calls(batch, 'ProductCheckList')} 处）",
         calls(batch, "ProductCheckList") == 1)
    c.ok(f"商品可见范围第二层调用它（实际 {calls(users, 'ProductCheckList')} 处）",
         calls(users, "ProductCheckList") == 1)
    c.ok("两个调用方都把「勾中的是谁」交给零件（checkedIds）",
         "checkedIds = " in batch and "checkedIds = seen," in users)
    c.ok("调用方自己那边不再拼三态头（TriStateCheckbox 只出现在零件里）",
         "TriStateCheckbox(" not in batch and "TriStateCheckbox(" not in users)

    # ── 6. 接线：反验脚本 + 两侧交叉引用 + KDoc 里的「为什么」─────────────
    c.section("6. 接线：反验脚本、账号管理页那侧的委托、KDoc 里的「为什么」")
    c.ok("反向验证脚本在（_tools/qa/_reverse_verify_product_check_list.py）", REVERSE.exists(),
         "没有它的话上面每一条都可能是空转")
    # CHG-0062：判据从"文件里提到过这个名字"收紧成"那两个常量指向本脚本" ——
    # 文档里提一句不算委托，**能跑的那两行**才算（`PART_CHECK` / `PART_REVERSE` 是
    # 账号管理页那侧唯一会去 .exists() 的两个路径）。
    c.ok("账号管理页的判据把清单侧委托给了本脚本（那两行常量指向本脚本）",
         'PART_CHECK = ROOT / "_tools/qa/_check_product_check_list.py"' in read(USERS_CHECK)
         and 'PART_REVERSE = ROOT / "_tools/qa/_reverse_verify_product_check_list.py"' in read(USERS_CHECK),
         "常量改了指不到本脚本 → 账号管理页那侧就不再盯这个零件了")
    c.ok("KDoc 留着「为什么」（两个页面语义不同、动作相同 —— 差别全在回调里）",
         "语义不同、动作相同" in raw and "所以差别全部落在回调里" in raw,
         "理由删了，下一个人就会把两边又合成一份")
    c.ok("KDoc 引着用户原话（能复用就复用）",
         "能复用就复用" in raw and "这个理念是最高级" in raw)

    print("\n" + "=" * 60)
    if c.fails:
        print(f"❌ {len(c.fails)} 项未通过（通过 {c.n_ok} 项）：")
        for label, _ in c.fails:
            print(f"   - {label}")
        return 1
    print(f"✅ 全部 {c.n_ok} 项通过：勾选商品零件（搜索 / 左分类栏 / 三态全选这一类 / 勾选行 / 自己滚 / "
          f"不许藏行）＋ 两个调用方都走它。")
    return 0


if __name__ == "__main__":
    if "--list" in sys.argv:
        print("== 它到底在查什么（勾选商品零件 ui/common/ProductCheckList.kt CHG-0062）==")
        print("0. 反空转 ＋ 复用：定义恰好一处、行走 ProductCardKit、分类栏走 ProductPicker")
        print("1. 搜索受控（词从外面来）、零件里过滤、有词能一键清掉、空态分两种")
        print("2. 左分类栏 ＋ 三态分类头（点它带 targetOn；选中那档没了回「全部」）")
        print("3. 勾选行：勾的是 checkedIds、整行可点、禁勾真的禁、下架有徽标")
        print("4. 清单自己滚（LazyColumn.fillMaxSize）、不套 verticalScroll、锁定与备注都不藏行")
        print("5. 两个调用方（批量操作页 / 商品可见范围第二层）都走这一份")
        print("6. 接线：反验脚本在、账号管理页那侧委托过来、KDoc 留着「为什么」与用户原话")
    else:
        sys.exit(main())
