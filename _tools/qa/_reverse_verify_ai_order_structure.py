#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CHG-0085 反向验证：把「订单结构三条」的判据逐条弄红一次，确认它们不是空转的。

为什么必须有这个脚本
--------------------
静态判据最危险的失效方式不是「报错」，而是**空转**：判据写得再漂亮，只要它盯的那行源码
被挪走、改名、或者换一种写法，它就会永远绿下去，而没有任何人会发现 —— 收口时「跑了一遍
全绿」和「判据其实什么都没在管」从输出上看一模一样。所以这一单的收口不能只跑一次
_tools/qa/_check_ai_order_structure.py 看它绿，还要逐条**注入一处真实的破坏**，看判据是否
**恰好红在那一条**上、而且只红在那一条上。

为什么「跳过」也算失败
----------------------
每条注入都要求原文在该文件里**恰好出现一次**：
  * 多于一次 = 锚点不唯一：改到哪一处不确定，改完是什么状态也不确定；
  * 零次     = 注入没生效（源码已经不是读到的样子），这条验证等于没做。
两种都记 [SKIP] 并计入失败 —— 宁可这里红，也不要带着「以为验过了」的错觉收工。

为什么不用文件的创建/删除（CREATIONS / DELETIONS）来判断
------------------------------------------------------
本脚本的判据全部钉在**显式文件路径**上（_check_ai_order_structure.py 自己的常量）。把文件
挪走或删掉只会让检查脚本自己崩掉，而崩掉就没有 [FAIL] 行 —— 本脚本判的恰恰是「期望的检查名
出现在 [FAIL] 行里」，于是「崩了」会被误判成「没红」。所以只认 [FAIL] 行。

注入的破坏分五类（对应判据的五种失效方式）
------------------------------------------
① 动作登记（AiWrite.kt）：常量、组、风险档、标题、参数名 —— 一条动作被登记成另一个样子；
② 角色门与三跳链路：白名单开错一边、端点/仓储/数据源任一跳改坏；
③ 处理器的两条硬规矩：preview 里偷写后端、commit 绕开自己的写方法；
④ 三张卡的**承诺**：每删掉一句都会让用户点确认时少知道一件事；
⑤ 资源 / 撤回 / 覆盖表 / 单测 / 文书：撤回挂错、覆盖表把「不做」塞回去、单测与说明书的钉子松掉。

用法
----
    python _tools/qa/_reverse_verify_ai_order_structure.py          # 真注入：改文件 -> 跑判据 -> 还原
    python _tools/qa/_reverse_verify_ai_order_structure.py --dry    # 只验锚点，一个字节都不改
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_ai_order_structure.py"

AI = "android/app/src/main/java/com/tapmoay/sorders/ai/"
W = AI + "AiWrite.kt"
H = AI + "AiWriteOrderHandlers.kt"
S = AI + "AiWriteService.kt"
SRC = AI + "AiWriteDataSource.kt"
RES = AI + "AiResources.kt"
RV = AI + "AiRevert.kt"
APIS = "android/app/src/main/java/com/tapmoay/sorders/data/remote/api/Apis.kt"
REPO = "android/app/src/main/java/com/tapmoay/sorders/data/repo/AppRepository.kt"
T = "android/app/src/test/java/com/tapmoay/sorders/ai/AiWriteTest.kt"
PT = "android/app/src/test/java/com/tapmoay/sorders/ai/AiWritePromptTest.kt"
WC = "_tools/ai/_write_coverage.py"
DOC = "docs/changes/CHG-0085.md"

# （说明, 相对路径, 原文, 替换成, 期望变红的检查名关键词）
MUTATIONS: list[tuple[str, str, str, str, str]] = [
    # ---- ① 动作登记在一处（AiWrite.kt）----
    (
        "id 常量抄错一个字母：orders.update_contact -> order.update_contact",
        W,
        'ORDERS_UPDATE_CONTACT = "orders.update_contact"',
        'ORDERS_UPDATE_CONTACT = "order.update_contact"',
        "id 常量只声明一次",
    ),
    (
        "转货挂错了组（挂成「我的下游价」）",
        W,
        '            risk = AiWriteRisk.HIGH,\n            group = G_ORDER,\n            blurb = "把这一张单上的货',
        '            risk = AiWriteRisk.HIGH,\n            group = G_MY_PRICE,\n            blurb = "把这一张单上的货',
        "转货：挂在「订单」组下",
    ),
    (
        "转货风险档降成 MEDIUM（它一次动两张单、撤不回来）",
        W,
        '            title = "转货（转给别的货主）",\n            risk = AiWriteRisk.HIGH,',
        '            title = "转货（转给别的货主）",\n            risk = AiWriteRisk.MEDIUM,',
        "转货是 HIGH 档",
    ),
    (
        "静默退回的标题把「货主无感」摘掉（这张卡最要紧的一句话）",
        W,
        'title = "退回派单池（货主无感）",',
        'title = "退回派单池",',
        "静默退回的标题把「货主无感」写在标题上",
    ),
    (
        "补联系信息风险档写成 HIGH（它补错了可以撤回，与 HIGH 不是一档）",
        W,
        '            title = "补联系信息",\n            risk = AiWriteRisk.MEDIUM,',
        '            title = "补联系信息",\n            risk = AiWriteRisk.HIGH,',
        "补联系信息是 MEDIUM 档",
    ),
    (
        "常量上方那句「三条都不是新能力」被改写成新能力（后人会以为要新建端点）",
        W,
        "三条都**不是新能力**：端点与手工入口早就有了",
        "三条都是新能力：要新建端点",
        "常量上方写着「三条都不是新能力」",
    ),
    # ---- ② 角色门（AiWrite.kt 白名单与 fail-closed 门）----
    (
        "转货被塞进货主白名单（货主拿到一张点了必然 403 的卡）",
        W,
        "        ORDERS_UPDATE_CONTACT,\n        ADDRESS_CREATE,",
        "        ORDERS_UPDATE_CONTACT,\n        ORDERS_TRANSFER,\n        ADDRESS_CREATE,",
        "转货**不**进 SHIPPER_ACTIONS",
    ),
    (
        "补联系信息从白名单里掉出去（货主连这张卡都看不见）",
        W,
        "        ORDERS_UPDATE_CONTACT,\n        ADDRESS_CREATE,",
        "        ADDRESS_CREATE,",
        "补联系信息进 SHIPPER_ACTIONS",
    ),
    (
        "白名单那条 fail-closed 注释被删（后人不明白为什么新动作要手动加）",
        W,
        "     * 2. 货主走 [SHIPPER_ACTIONS] 白名单（新加的动作不进白名单 = 货主拿不到）；",
        "// 货主能用的动作",
        "白名单那条 fail-closed 注释还在",
    ),
    (
        "角色门从白名单放行改成黑名单排除（新动作默认对货主敞开）",
        W,
        "it.id in SHIPPER_ACTIONS && (!it.memberOnly || member)",
        "it.id !in SHIPPER_ACTIONS && (!it.memberOnly || member)",
        "角色门的实现是按白名单放行",
    ),
    # ---- ③ 参数形状（AiWrite.kt 三条规格）----
    (
        "转货参数里混进编号（to_shipper -> to_shipper_id，模型会照着编一个）",
        W,
        '                    "to_shipper", "转给谁（系统里已有的货主）",',
        '                    "to_shipper_id", "转给谁（系统里已有的货主）",',
        "⛔ 转货参数里没有 to_shipper_id",
    ),
    (
        "转货的 lines 退化成单行 NUMBER（多行明明是这个动作的难点）",
        W,
        '                    "lines", "转哪几件", kind = AiWriteParamKind.TEXT,',
        '                    "lines", "转哪几件", kind = AiWriteParamKind.NUMBER,',
        "转货的 lines 是 TEXT",
    ),
    (
        "转货提示里删掉「留空 = 整单转出」（模型会以为必须给明细）",
        W,
        'hint = "**留空 = 整单转出**。只转一部分时传数组：" +',
        'hint = "只转一部分时传数组：" +',
        "转货提示里写明留空 = 整单转出",
    ),
    (
        "静默退回参数里混进 order_id",
        W,
        '                AiWriteParam("order", "订单", required = true, hint = "必填，订单号"),\n                AiWriteParam(\n                    "reason", "退回原因",',
        '                AiWriteParam("order_id", "订单", required = true, hint = "必填，订单号"),\n                AiWriteParam(\n                    "reason", "退回原因",',
        "⛔ 静默退回参数里没有任何 xxx_id",
    ),
    (
        "补联系信息参数里混进 boss_phone_id",
        W,
        'AiWriteParam("boss_phone", "下单人电话", hint = "可选"),',
        'AiWriteParam("boss_phone_id", "下单人电话", hint = "可选"),',
        "⛔ 补联系信息参数里没有任何 xxx_id",
    ),
    # ---- ④ 处理器：preview 不写后端、commit 只认 payload ----
    (
        "静默退回在预览里就把单退回去了（预览不再是「什么都没动过」）",
        H,
        '        val reason = AiWriteArgs.str(params, "reason")?.let { AiWriteArgs.text(it, "退回理由", max = 200) }',
        '        val reason = AiWriteArgs.str(params, "reason")?.let { AiWriteArgs.text(it, "退回理由", max = 200) }\n        ds.releaseOrder(order.id, "先退一下")',
        "静默退回：预览里一个字都不写后端",
    ),
    (
        "转货的 commit 写错了方法名（提交这一步空转）",
        H,
        "        ds.transferOrderLines(\n            orderId = payload.reqLong(\"order_id\"),",
        "        ds.transferOrderLinesX(\n            orderId = payload.reqLong(\"order_id\"),",
        "转货：提交里真的调了写方法",
    ),
    (
        "静默退回借「撤回派单」的动作 id 实现（两条动作被合并的第一现场）",
        H,
        "    override val actionId = AiWrites.ORDERS_RELEASE",
        "    override val actionId = AiWrites.ORDERS_RELEASE\n    private val mergeCandidate = AiWrites.ORDERS_RECALL",
        "⛔ 静默退回不许借「撤回派单」的动作实现",
    ),
    (
        "终态三兄弟少一个（已退货的单会被当成在途单推司机）",
        H,
        'private val FINISHED_STATUSES = setOf("DELIVERED", "CANCELLED", "RETURNED")',
        'private val FINISHED_STATUSES = setOf("DELIVERED", "CANCELLED")',
        "终态三兄弟的口径与后端同一份",
    ),
    (
        "转货一次最多 10 行被悄悄放到 20 行",
        H,
        "private const val MAX_TRANSFER_LINES = 10",
        "private const val MAX_TRANSFER_LINES = 20",
        "转货：一次最多 10 行的常量",
    ),
    (
        "补联系信息不再校验电话（字母汉字会被当成号码写进库里）",
        H,
        '    InputRules.phoneError(v)?.let { throw AiWriteArgException("「${cn}」${it}") }',
        '    if (v.isEmpty()) throw AiWriteArgException("「${cn}」不能为空")',
        "补联系信息的电话校验用 InputRules.phoneError",
    ),
    (
        "补联系信息的 payload 变成「整张单照抄回去」而不是只报改动字段",
        H,
        "                for (c in changes) put(c.key, c.value)",
        '                put("remark", "顺手清一下备注")',
        "补联系信息的 payload 逐项落改动字段",
    ),
    # ---- ⑤ 三张卡的承诺（逐句）----
    (
        "转货卡删掉「撤不回来」（用户点确认时以为还能反悔）",
        H,
        '                add("⛔ 这一次会同时改两张单（源单少几件、目标单多几件，源单还可能作废），撤不回来；要转回去得再发起一次反向的转货")',
        '                add("⛔ 这一次会同时改两张单")',
        "转货卡：⛔ 撤不回来",
    ),
    (
        "转货卡把「新开那张会跟着原司机」说反了",
        H,
        '"这一单现在在 ${order.driverLabel} 手上：新开的那张会跟着他一起派出去" +',
        '"这一单现在在 ${order.driverLabel} 手上：新开的那张不会跟着他" +',
        "转货卡：新开那张会跟着原司机",
    ),
    (
        "静默退回卡不再说「货主端不会有任何变化」（这一条的全部意义就在这句话上）",
        H,
        'add("不会有任何变化：他看到的还是「${order.statusCn}」、还是这位司机，也收不到任何提醒")',
        'add("货主那边我们就不打扰了")',
        "静默退回卡：货主端不会有任何变化",
    ),
    (
        "静默退回卡删掉与「撤回派单」的对比句",
        H,
        'add("（这就是这个动作的定义 —— 与「撤回派单」唯一的区别就在这里：那一条会告诉货主）")',
        "// （对比句被删掉了）",
        "静默退回卡：这是定义、不是漏发",
    ),
    (
        "补联系卡删掉「补错了可以撤回」",
        H,
        'add("补错了可以撤回（撤回把这几项改回原来的值）")',
        "// （撤回提示被删掉了）",
        "补联系卡：补错了可以撤回",
    ),
    (
        "补联系卡把空旧值的提示从「（空）」改成别的（用户看不出原来有没有值）",
        H,
        'AiRevertJson.textOf(before?.get(key)).ifBlank { "（空）" }',
        'AiRevertJson.textOf(before?.get(key)).ifBlank { "无" }',
        "补联系卡：旧值为空时说「（空）」",
    ),
    (
        "补联系卡不再写明「只能补联系信息」",
        H,
        'add("这一条只能补联系信息：送货地址、配送说明、备注那些要派单员才能改")',
        "// （边界说明被删掉了）",
        "补联系卡：只能补联系信息（别的字段要派单员）",
    ),
    (
        "转货卡的收货人空白警告被删（司机到了没有人可打）",
        H,
        '                        "⚠️ 这一单的收货人姓名和电话都是空的：新单会照着抄一份空白" +',
        '                        "" +',
        "转货卡：收货人全空时的警告",
    ),
    # ---- ⑥ 三跳链路（Apis -> AppRepository -> ai/）----
    (
        "静默退回的端点路径改成 recall（两条动作在 API 层被混成一条）",
        APIS,
        '@POST("orders/{orderId}/release")',
        '@POST("orders/{orderId}/recall")',
        "端点：静默退回是 POST orders/{orderId}/release",
    ),
    (
        "仓储的静默退回改调撤回（货主会收到他不该收到的通知）",
        REPO,
        "api.orderApi.releaseOrder(orderId, com.tapmoay.sorders.data.remote.dto.OrderReleaseBody(reason))",
        "api.orderApi.recallOrder(orderId, com.tapmoay.sorders.data.remote.dto.OrderReleaseBody(reason))",
        "仓储：静默退回（带 OrderReleaseBody）",
    ),
    (
        "数据源少一跳：补联系信息的方法名被改掉",
        SRC,
        "override suspend fun updateOrderContact(orderId: Long, fields: JsonObject)",
        "override suspend fun updateOrderContacts(orderId: Long, fields: JsonObject)",
        "数据源：补联系信息",
    ),
    (
        "补联系信息的端点上标成 POST（手工与 AI 会走两条路）",
        APIS,
        '@PATCH("orders/{orderId}/contact")',
        '@POST("orders/{orderId}/contact")',
        "端点：补联系信息是 PATCH orders/{orderId}/contact",
    ),
    # ---- ⑦ 资源 / 撤回 / 覆盖表 / 单测 / 文书 ----
    (
        "补联系信息从 ORDER 资源里摘掉（一键撤回跟着没了）",
        RES,
        "            update(AiWrites.ORDERS_UPDATE_CONTACT),",
        "            update(AiWrites.ORDERS_FREIGHT),",
        "补联系信息挂 ORDER 资源的 update",
    ),
    (
        "资源的中文名表里少一个联系字段（撤回时卡片上会出现原始键名）",
        RES,
        '            "contact_boss_phone" to "下单人电话",',
        '            "contact_boss_phone" to "手机",',
        "资源中文名里有「下单人电话」",
    ),
    (
        "转货被当成可撤回的动作（用户会看到一个点了没反应的撤回按钮）",
        RV,
        "            listOf(AiWrites.ORDERS_TRANSFER),",
        "            listOf(AiWrites.ORDERS_UPDATE_CONTACT),",
        "转货：已声明撤不回来（UNDO_NONE 里有它一条）",
    ),
    (
        "转货那条「不做撤回」的理由被抽掉只剩一句废话",
        RV,
        '"转货一次动两张单（源单少了那几行、目标单多了那几行，搬空了源单还会作废）——" +',
        '"转货撤不回来" +',
        "转货的理由：它一次动两张单",
    ),
    (
        "转货被塞回覆盖表的「不做」桶（台账与覆盖表互相矛盾）",
        WC,
        '    ("POST", "products/{}/image"): "上传类：要一个文件，模型给不出（v3.7 永久排除）",',
        '    ("POST", "orders/{}/transfer"): "本轮不开放",\n    ("POST", "products/{}/image"): "上传类：要一个文件，模型给不出（v3.7 永久排除）",',
        "POST orders/{}/transfer 不再挂在「不做」里",
    ),
    (
        "覆盖表里删掉「两条只给派单员」那句",
        WC,
        "    # ⚠️ 两条都**只给派单员**（后端 `order:dispatch` / `order:recall`），货主连清单里都看不见。",
        "    # 两条都归派单员。",
        "两条只给派单员这件事写在覆盖表里",
    ),
    (
        "覆盖表里删掉「这一扇门存在的理由」（终态单也放行）",
        WC,
        "    #     而改单在终态单上会被拒 ——「货送完了才发现号码写错」正是这一扇门存在的理由；",
        "    #     而改单在终态单上会被拒；",
        "补联系信息那条写明终态单放行（这一扇门存在的理由）",
    ),
    (
        "单测里的角色矩阵被改成 assertTrue（货主能转货 —— 这条断言本身失效了）",
        T,
        'assertFalse("转货会同时改两张单，货主只能发起退货申请", AiWrites.allows(shipper, AiWrites.ORDERS_TRANSFER))',
        'assertTrue("转货会同时改两张单，货主只能发起退货申请", AiWrites.allows(shipper, AiWrites.ORDERS_TRANSFER))',
        "单测里钉住了角色矩阵：货主不能转货",
    ),
    (
        "单测里的动作总数上界从 165 放成 200（以后加动作不会再有人被提醒抬上限）",
        T,
        "AiWrites.ALL.size <= 165",
        "AiWrites.ALL.size <= 200",
        "单测里钉住了动作总数上界 165",
    ),
    (
        "说明书上限被改回 26000（说明书已经 26096 字符，断言会一直红着或被人调松）",
        PT,
        "（上限 27000）",
        "（上限 26000）",
        "说明书上限已抬到 27000",
    ),
    (
        "变更单里删掉台账号（收口时要能顺着 L-54 找到台账那一行）",
        DOC,
        "（**L-54**，台账末尾「第七次收口」那一行；",
        "（台账号见台账末尾「第七次收口」那一行；",
        "变更单里写了台账 L-54",
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

