#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CHG-0084 反向验证：把「下游定价 3 写 + 2 读」的判据逐条弄红一次，确认它们不是空转的。

为什么必须有这个脚本
--------------------
静态判据最危险的失效方式不是「报错」，而是**空转**：判据写得再漂亮，只要它盯的那行源码
被挪走、改名、或者换一种写法，它就会永远绿下去，而没有任何人会发现 —— 收口时「跑了一遍
全绿」和「判据其实什么都没在管」从输出上看一模一样。所以这一单的收口不能只跑一次
_tools/qa/_check_ai_my_prices.py 看它绿，还要逐条**注入一处真实的破坏**，看判据是否
**恰好红在那一条**上、而且只红在那一条上。

为什么「跳过」也算失败
----------------------
每条注入都要求原文在该文件里**恰好出现一次**：
  * 多于一次 = 锚点不唯一：改到哪一处不确定，改完是什么状态也不确定；
  * 零次     = 注入没生效（源码已经不是读到的样子），这条验证等于没做。
两种都记 [SKIP] 并计入失败 —— 宁可这里红，也不要带着「以为验过了」的错觉收工。

为什么不用文件的创建/删除（CREATIONS / DELETIONS）来判断
------------------------------------------------------
本脚本的判据全部钉在**显式文件路径**上（_check_ai_my_prices.py 自己的常量）。把文件挪走
或删掉只会让检查脚本自己崩掉，而崩掉就没有 [FAIL] 行 —— 本脚本判的恰恰是「期望的检查名
出现在 [FAIL] 行里」，于是「崩了」会被误判成「没红」。所以只认 [FAIL] 行。

用法
----
    python _tools/qa/_reverse_verify_ai_my_prices.py          # 真注入：改文件 -> 跑判据 -> 还原
    python _tools/qa/_reverse_verify_ai_my_prices.py --dry    # 只验锚点，一个字节都不改
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_ai_my_prices.py"

AI = "android/app/src/main/java/com/tapmoay/sorders/ai/"
W = AI + "AiWrite.kt"
P = AI + "AiWriteMyPrices.kt"
H = AI + "AiWriteMyPriceHandlers.kt"
S = AI + "AiWriteDataSource.kt"
RES = AI + "AiResources.kt"
RV = AI + "AiRevert.kt"
CAT = AI + "AiReadCatalog.kt"
T = "android/app/src/test/java/com/tapmoay/sorders/ai/AiWriteTest.kt"
WC = "_tools/ai/_write_coverage.py"
RC = "_tools/ai/_read_coverage.py"

# （说明, 相对路径, 原文, 替换成, 期望变红的检查名关键词）
MUTATIONS: list[tuple[str, str, str, str, str]] = [
    # ---- ① 动作登记在一处（AiWrite.kt）----
    (
        "id 常量少一个 s：shipper_price.set -> shipper_prices.set",
        W,
        'SHIPPER_PRICE_SET = "shipper_price.set"',
        'SHIPPER_PRICE_SET = "shipper_prices.set"',
        "三个动作 id 只在 AiWrites 里定义一处",
    ),
    (
        "组名换一个说法（与派单员给的专属价混成一层）",
        W,
        'const val G_MY_PRICE = "我的下游价"',
        'const val G_MY_PRICE = "我给下游的价"',
        "「我的下游价」自己有组名",
    ),
    (
        "新域没接进 AiWrites.ALL：这一行指向另一个域的动作",
        W,
        "            AiWriteMyPrices.ACTIONS",
        "            AiWriteBaseData.ACTIONS",
        "新域接进了 AiWrites.ALL",
    ),
    (
        "SHIPPER_ACTIONS 里少登记一条（恢复那条掉了）",
        W,
        "        SHIPPER_PRICE_SET,\n        SHIPPER_PRICE_DELETE,\n        SHIPPER_PRICE_RESTORE,",
        "        SHIPPER_PRICE_SET,\n        SHIPPER_PRICE_DELETE,",
        "三条都进了 SHIPPER_ACTIONS",
    ),
    # ---- ② 两条手写动作的形状（AiWriteMyPrices.kt）----
    (
        "删价那条不再只给批发商货主（memberOnly 掉了）",
        P,
        "            memberOnly = true,\n        ),\n        // 恢复：",
        "        ),\n        // 恢复：",
        "三条都标了 memberOnly",
    ),
    (
        "删价那条风险档写高了（说错了 HIGH），与「说一句就能改回去」的档位不符",
        P,
        '            risk = AiWriteRisk.MEDIUM,\n            group = AiWrites.G_MY_PRICE,\n            blurb = "把某一条下游价删掉',
        '            risk = AiWriteRisk.HIGH,\n            group = AiWrites.G_MY_PRICE,\n            blurb = "把某一条下游价删掉',
        "两条都是 MEDIUM 档",
    ),
    (
        "恢复那条 id 抄成了定价那条（不是 undoOnly 的恢复动作）",
        P,
        "id = AiWrites.SHIPPER_PRICE_RESTORE,",
        "id = AiWrites.SHIPPER_PRICE_SET,",
        "恢复动作走 restoreAction",
    ),
    (
        "恢复动作没真的调数据源的恢复方法（调用被改坏）",
        P,
        "call = { ds, id -> ds.restoreMyPrice(id) },",
        "call = { ds, id -> ds.restoreMyPrice(id + 0) },",
        "恢复动作真的调数据源的 restoreMyPrice",
    ),
    (
        "单价参数退化成文本（模型给的是数，不是随手一段文字）",
        P,
        "kind = AiWriteParamKind.NUMBER,",
        "kind = AiWriteParamKind.TEXT,",
        "单价是 NUMBER",
    ),
    (
        "参数里混进了编号（price_id）：模型只给名字，App 自己换编号",
        P,
        '                AiWriteParam(name = "price", cn = "单价（元）", hint = "可选。同一个商品有多条价时用它指认是哪一条"),',
        '                AiWriteParam(name = "price_id", cn = "单价（元）", hint = "可选。同一个商品有多条价时用它指认是哪一条"),',
        "参数里没有 xxx_id",
    ),
    # ---- ③ 两条处理器（AiWriteMyPriceHandlers.kt）----
    (
        "删价那条的 prepare 不再问会员身份",
        H,
        "    override suspend fun prepare(params: JsonObject): AiWriteOutcome {\n        requireMemberShipper(ds)\n\n        // 只认",
        "    override suspend fun prepare(params: JsonObject): AiWriteOutcome {\n\n        // 只认",
        "两条 prepare 里都问了一次会员身份",
    ),
    (
        "会员闸只在注释里（判断被短路成 false）",
        H,
        "if (!ds.isMemberShipper())",
        "if (false)",
        "会员闸真的读了 isMemberShipper",
    ),
    (
        "被拦下时不给路：用户不知道该怎么变成批发商货主",
        H,
        "在「货主管理」里把你设成批发商",
        "请联系管理员",
        "被拦下时给出路",
    ),
    (
        "删价的 prepare 连回收站一起读（再删一次会命中 0 行）",
        H,
        "        val all = ds.myPrices()",
        "        val all = ds.myPrices(includeDeleted = true)",
        "删价的 prepare 只读没被删掉的行",
    ),
    (
        "定价的 prepare 不再读回收站（于是复活软删那行看不见）",
        H,
        "ds.myPrices(includeDeleted = true)",
        "ds.myPrices(includeDeleted = false)",
        "定价的 prepare 连回收站一起读",
    ),
    (
        "prepare 里写后端（一次写数据源调用混进了只读阶段）",
        H,
        "        val all = ds.myPrices()",
        "        val all = ds.myPrices()\n        ds.deleteMyPrice(0)",
        "prepare 里一个字都不许写后端",
    ),
    (
        "定价的 commit 不再只认 payload 里的编号",
        H,
        'productId = payload.reqLong("product_id")',
        'productId = payload.reqLong("product")',
        "commit 只认 payload 里的编号（定价）",
    ),
    (
        "删价的 commit 不再只认 payload 里的编号",
        H,
        'ds.deleteMyPrice(payload.reqLong("price_id"))',
        'ds.deleteMyPrice(payload.reqLong("id"))',
        "commit 只认 payload 里的编号（删价）",
    ),
    (
        "入参里混进了 shipper_id（派单员代设，写的必须是 current.id）",
        H,
        'payload["contact_id"]?.jsonPrimitive?.longOrNull',
        'payload["contact_id"]?.jsonPrimitive?.longOrNull ?: payload["shipper_id"]?.jsonPrimitive?.longOrNull',
        "入参里没有 shipper_id",
    ),
    (
        "下游联系人被当成必填编号（默认价那一档没有联系人）",
        H,
        'payload["contact_id"]?.jsonPrimitive?.longOrNull',
        'payload.reqLong("contact_id")',
        "下游联系人是可空编号",
    ),
    (
        "下游名册的排除词表没了（「所有下游」会被当成联系人查）",
        H,
        "private val ALL_DOWNSTREAM_WORDS: Set<String> = setOf(",
        "private val ALL_DOWNSTREAM_WORDZ: Set<String> = setOf(",
        "这一类说法不当人名册查",
    ),
    (
        "价格比较不再走数字（后端可能下发 8.5000）",
        H,
        "private fun sameMoney(raw: String?, want: BigDecimal): Boolean",
        "private fun sameMoneyText(raw: String?, want: String): Boolean",
        "价格比较走数字",
    ),
    (
        "多条价时替他挑一条（不再用单价指认）",
        H,
        "要删哪一条？说单价我就知道是哪条",
        "说个大概就行",
        "多条价时用单价指认",
    ),
    # ---- ④ 两张卡的文案 ----
    (
        "定价卡不再说「再设一次是复活软删那一行」",
        H,
        "（后台会把它复活——不是新建一条）",
        "（后台会自动更新这一条）",
        "定价卡如实说「再设一次是复活软删那一行」",
    ),
    (
        "卡片不再说「只影响以后新下的单」（老单会不会被追改）",
        H,
        '                    "只影响以后新下的单：已经下过的单一个字节都不动",',
        '                    "只管以后新下的单：已经下过的单一个字节都不动",',
        "两张卡都写明「只影响以后新下的单」",
    ),
    (
        "卡片不再说清「这本下游账是他自己的」（公司那边的账受不受影响）",
        H,
        '    "只动你自己那一本下游账：公司（派单员）那边的账一个数字都不会变"',
        '    "只动你自己那一本下游账：跟公司那边没关系"',
        "两张卡都说清这本账是他自己的",
    ),
    (
        "删价卡不再说后台是伪装删除（能不能放回来）",
        H,
        "伪装删除",
        "软删除",
        "删价卡说清后台是伪装删除、能放回来",
    ),
    (
        "删价卡不再写回落口径（默认价 / 订单行单价）",
        H,
        '                    if (contact == null) {\n                        "删的是默认价：没单独定过价的下游一起回落订单行单价（你这本账按公司给你的价算）"\n                    } else {\n                        "删的是他的专属价：他回落你的默认价；没有默认价就回落订单行单价"\n                    },',
        '                    if (contact == null) {\n                        "删的是默认价：没单独定过价的下游一起按订单行单价重算（你这本账按公司给你的价算）"\n                    } else {\n                        "删的是他的专属价：他回到你的默认价；没有默认价就按订单行单价重算"\n                    },',
        "删价卡写明回落口径",
    ),
    # ---- ⑤ 数据源五条与三跳链路（AiWriteDataSource.kt）----
    (
        "第三跳断了：删价那条没调到 repo 的删除方法",
        S,
        "repo.deleteShipperPrice(id)",
        "repo.deleteShipperPrice(rowId)",
        "三跳链路的第三跳",
    ),
    (
        "恢复那条写成表达式体（repo 的返回类型不是 Unit，编译不过）",
        S,
        "    override suspend fun restoreMyPrice(id: Long) {",
        "    override suspend fun restoreMyPrice(id: Long) =",
        "恢复那条是块体",
    ),
    (
        "读路径没走既有 repo 方法（读回的是另一档口径）",
        S,
        "repo.shipperPrices(null, null, includeDeleted)",
        "repo.shipperPrices(null, null, null)",
        "读路径也走既有 repo 方法",
    ),
    (
        "快照里没有 shipper_price 分支（红线逐个资源对账会缺一个）",
        S,
        '"shipper_price" -> null',
        '"shipper_prices" -> null',
        "快照里有 shipper_price 分支",
    ),
    # ---- ⑥ 资源与撤回（AiResources.kt / AiRevert.kt）----
    (
        "资源的 idKey 换成了恢复动作的入参名（撤回会找不到那一条）",
        RES,
        'idKey = "price_id",',
        'idKey = "target_id",',
        "资源 idKey 是 price_id",
    ),
    (
        "资源里没有删除动作（只剩成对那一半）",
        RES,
        "            delete(AiWrites.SHIPPER_PRICE_DELETE),\n            paired(",
        "            paired(",
        "资源里有删除动作",
    ),
    (
        "资源没收录进 TABLE（红线逐个资源对账会缺一个）",
        RES,
        "        INVOICE,\n    )",
        "    )",
        "资源收录进 TABLE",
    ),
    (
        "恢复动作的映射写成了删除动作的入参名（撤回只认编号，写错就撤不回）",
        RES,
        'AiInverse(AiWrites.SHIPPER_PRICE_RESTORE, mapOf("target_id" to AiRevert.ID))',
        'AiInverse(AiWrites.SHIPPER_PRICE_RESTORE, mapOf("price_id" to AiRevert.ID))',
        "恢复动作的映射用的是恢复动作自己的参数名 target_id",
    ),
    (
        "读回字段少一个（下游联系人不见了，改价时看不出这一条是给谁的）",
        RES,
        'readKeys = setOf("product_id", "contact_id", "unit_price"),',
        'readKeys = setOf("product_id", "unit_price"),',
        "读回字段三个",
    ),
    (
        "改价那条溜进了资源（upsert 在写之前不知道撤到哪一条）",
        RES,
        "        // 下游价（2026-10-08 CHG-0084）：只有「删 / 放回来」成对，改价那条走 UNDO_NONE",
        "        // 下游价（2026-10-08 CHG-0084）：只有「删 / 放回来」成对，改价那条走 UNDO_NONE\n        // AiWrites.SHIPPER_PRICE_SET（不该出现，注入用）",
        "改价那条**不进**资源",
    ),
    (
        "UNDO_NONE 里那条专门理由挂错了动作",
        RV,
        "            listOf(AiWrites.SHIPPER_PRICE_SET),",
        "            listOf(AiWrites.SHIPPER_PRICE_RESTORE),",
        "改价那条在 UNDO_NONE 里有一条专门理由",
    ),
    (
        "理由里不点名出路（用户不知道该说哪句话改回去）",
        RV,
        "把 XXX 的价改成 YYY",
        "改回去",
        "理由里点名出路",
    ),
    (
        "理由里不说删价那条有撤回按钮（其实有）",
        RV,
        "删价是有「撤回」按钮的",
        "删价也能撤",
        "理由里点明删价那条有撤回按钮",
    ),
    (
        "把先例那条（核销）的 UNDO_NONE 改坏了",
        RV,
        "            listOf(AiWrites.MY_LEDGER_SETTLE),",
        "            listOf(AiWrites.MY_LEDGER_RESTORE),",
        "先例那条（核销）还在",
    ),
    # ---- ⑦ 覆盖表与生成物 ----
    (
        "POST /shipper-prices 又挂回了 EXCLUDED（口径倒退）",
        WC,
        "    # 用户明确说永久不做（目标④）。",
        '    ("POST", "shipper-prices"): "下游定价：本轮不开放",\n    # 用户明确说永久不做（目标④）。',
        "POST /shipper-prices 不再挂在 EXCLUDED 里",
    ),
    (
        "DELETE /shipper-prices/{id} 又挂回了 EXCLUDED",
        WC,
        '("POST", "customers/merge")',
        '("DELETE", "shipper-prices/{}")',
        "DELETE /shipper-prices/{id} 不再挂在 EXCLUDED 里",
    ),
    (
        "POST /shipper-prices/{id}/restore 又挂回了 EXCLUDED",
        WC,
        '("POST", "customers/merge")',
        '("POST", "shipper-prices/{}/restore")',
        "POST /shipper-prices/{id}/restore 不再挂在 EXCLUDED 里",
    ),
    (
        "覆盖表里没有这次改口径的来龙去脉（谁在什么时候开的）",
        WC,
        "CHG-0084 开给 AI",
        "CHG-0084 开给货主",
        "覆盖表里留着这次改口径的来龙去脉",
    ),
    (
        "读覆盖表里又把可定价商品写成「不做」",
        RC,
        "MIN_ENDPOINTS = 100",
        'MIN_ENDPOINTS = 100\nNOT_DOING_ONE = "shipper_prices.list_priceable_products"',
        "读覆盖表里那条「不做」的注释块已删",
    ),
    (
        "读覆盖表里又把价目表写成「不做」",
        RC,
        "MIN_ENDPOINTS = 100",
        'MIN_ENDPOINTS = 100\nNOT_DOING_TWO = "shipper_prices.list_shipper_prices"',
        "读覆盖表里第二条「不做」也没了",
    ),
    (
        "生成物（Android 侧读动作目录）里少一条读动作",
        CAT,
        "shipper_prices.list_shipper_prices",
        "shipper_prices.list_fake",
        "生成物（Android 侧读动作目录）里两条都在",
    ),
    # ---- ⑧ 单测 ----
    (
        "动作数上界没跟着抬（下一批加动作时会先撞到这堵墙）",
        T,
        "AiWrites.ALL.size <= 176",
        "AiWrites.ALL.size <= 162",
        "动作数上界抬到了 176",
    ),
    (
        "单测里没有可定价商品的夹具（判据会以为这一域没被测过）",
        T,
        "var myPriceProductRows: MutableList<AiMyPriceProduct>",
        "var myPriceProductRowz: MutableList<AiMyPriceProduct>",
        "单测里有可定价商品的夹具",
    ),
]


def read_src(rel: str) -> tuple[str, bool]:
    raw = (ROOT / rel).read_bytes()
    crlf = b"\r\n" in raw
    return raw.decode("utf-8").replace("\r\n", "\n"), crlf


def write_src(rel: str, text: str, crlf: bool) -> None:
    data = text.replace("\n", "\r\n") if crlf else text
    (ROOT / rel).write_bytes(data.encode("utf-8"))


def restore_src(rel: str, text: str, crlf: bool, expect: bytes) -> None:
    write_src(rel, text, crlf)
    back = (ROOT / rel).read_bytes()
    if back != expect:
        print("  [FATAL] 还原后字节不一致：{}".format(rel))
        raise SystemExit(2)


def run_check():
    # 子进程强制 UTF-8：Windows 控制台默认是 GBK，判据里的中文标签一旦被按 GBK 编码，
    # 这一侧按 UTF-8 解出来就是乱码，expect 关键词会永远匹配不上（全部误报 MISS）。
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(CHECK)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


def fails_of(out: str) -> list[str]:
    return [line.strip() for line in out.splitlines() if line.strip().startswith("[FAIL]")]


def verdict(expect: str, proc) -> tuple[bool, str]:
    lines = fails_of(proc.stdout + proc.stderr)
    if proc.returncode == 0:
        return False, "判据**没红**（退出码 0）—— 这条检查是空转的"
    hit = [line for line in lines if expect in line]
    if hit:
        return True, hit[0]
    return False, "红了但不是这条（实际红 {} 条）：{}".format(len(lines), " | ".join(lines[:3]))


def dry_run() -> int:
    print("== 只验锚点（--dry）：一个字节都不改 ==")
    bad = 0
    for idx, (why, rel, old, _new, expect) in enumerate(MUTATIONS, start=1):
        text, _crlf = read_src(rel)
        n = text.count(old)
        if n == 1:
            print("  [OK]  {}. {} :: {}".format(idx, rel, why))
        else:
            bad += 1
            print("  [BAD] {}. {} :: {} —— 原文出现 {} 次（期望 1 次）；期望判据：{}".format(idx, rel, why, n, expect))
    print()
    if bad:
        print("❌ {} 条锚点不唯一 / 找不到。".format(bad))
        return 1
    print("✅ {} 条锚点全部唯一命中。".format(len(MUTATIONS)))
    return 0


def main() -> int:
    if "--dry" in sys.argv:
        return dry_run()

    total = len(MUTATIONS) + 1
    print("== 0. 前提：源码完好时判据必须全绿 ==")
    proc = run_check()
    if proc.returncode != 0:
        print("  [FATAL] 起点判据就是红的，没法做反向验证（先修好再加注入）。")
        for line in fails_of(proc.stdout + proc.stderr)[:10]:
            print("    " + line)
        return 2
    for line in (proc.stdout + proc.stderr).splitlines():
        if "全部" in line and "通过" in line:
            print("  [OK]  " + line.strip())
            break
    else:
        print("  [OK]  判据退出码 0")

    print()
    print("== 1. 逐条注入 -> 跑判据 -> 还原 ==")
    bad = 0
    for idx, (why, rel, old, new, expect) in enumerate(MUTATIONS, start=1):
        text, crlf = read_src(rel)
        n = text.count(old)
        if n != 1:
            bad += 1
            print("  [SKIP] {}. {} :: {} —— 原文出现 {} 次（期望 1 次）".format(idx, rel, why, n))
            continue
        before = (ROOT / rel).read_bytes()
        try:
            write_src(rel, text.replace(old, new), crlf)
            got = run_check()
            ok, detail = verdict(expect, got)
        finally:
            restore_src(rel, text, crlf, before)
        if ok:
            print("  [OK]   {}. {} :: {} -> 判据红在「{}」".format(idx, rel, why, expect))
        else:
            bad += 1
            print("  [MISS] {}. {} :: {} -> {}".format(idx, rel, why, detail))

    print()
    print("== 2. 收尾：文件都还原之后，判据必须重新全绿 ==")
    proc = run_check()
    if proc.returncode == 0:
        print("  [OK]  判据重新全绿（没有文件被留在改坏的状态）")
    else:
        bad += 1
        print("  [MISS] 还原之后判据仍然是红的 —— 有文件没还原干净")
        for line in fails_of(proc.stdout + proc.stderr)[:10]:
            print("    " + line)

    print()
    if bad:
        print("❌ {}/{} 条不成立。".format(bad, total))
        return 1
    print("✅ {}/{} 全部成立：每条判据都被单独弄红过一次，而且只在它自己身上红。".format(total, total))
    return 0


if __name__ == "__main__":
    sys.exit(main())
