# -*- coding: utf-8 -*-
r"""反向验证「联系人可以挑 / 可以绑在地点与线路上」这条红线**真的会红**（2026-09-24）。

## 为什么这条要反向验证
它的判据大多是"某段代码里必须出现某个零件 / 某个回填"，这类判据有三种典型失效方式，
每一种都必须被单独证明会红：

1. **判据变成空转**：`fillReceiver` 被改名/搬走之后，如果判据只写"别处不许再定义一份"，
   它会安静地全绿 —— 本脚本把定义改名，必须报红（**0 处也红**）。
2. **抽取失效 → 类体/函数体取到空串**：`ShipperLocation` 是文件里**最后一个类**，
   用 `class …(.*?)\nclass ` 去截会截到空串，于是"有没有那两列""是不是外键"全变成
   空体上恒真。本脚本把列名改掉，必须报红。
3. **只扫整个文件、不扫函数体**：`applyPlace`（共享地点）与 `applyLocation`（我的地点）
   在同一个文件里，判据要是不限定函数体，往共享那一支塞个 `p.contactName` 就骗过去了。
   本脚本专门往 `applyPlace` 的**函数体里**塞一次。

另外五条打"静默解绑"这条最隐蔽的路：地点编辑不回填、保存不带联系人、AI 改地点不回填、
PATCH 丢掉 `None` 三档语义、后端补列被删掉。还有两条打"两处消费"（又有人把名册摊成下拉）
与"判据清单自己指向不存在的文件"。

⚠️ 快照/还原按**字节**做，跑完逐字节核对（本项目栽过"注入把 bug 留在源码里"）。

用法：python _tools/qa/_reverse_verify_contact_binding.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_contact_binding.py"
CHECK_REL = "_tools/qa/_check_contact_binding.py"

AND = "android/app/src/main/java/com/tapmoay/sorders"
ADDR_VM = f"{AND}/ui/shipper/AddressViewModel.kt"
ADDR_SCREEN = f"{AND}/ui/shipper/AddressScreen.kt"
ORDER_VM = f"{AND}/ui/shipper/OrderCreateViewModel.kt"
FILL = f"{AND}/ui/common/ContactFill.kt"
DTOS = f"{AND}/data/remote/dto/Dtos.kt"
AI_SVC = f"{AND}/ai/AiWriteService.kt"
# ⛔ 2026-09-26 修：`contactName = fields.str("contact_name") ?: cur.contactName` 这一行随实现搬进了
#    `AiWriteDataSource.kt`（服务只剩薄派发）。只改目标文件，锚点原文不动。
AI_DATA = f"{AND}/ai/AiWriteDataSource.kt"
TEST = "android/app/src/test/java/com/tapmoay/sorders/ui/common/ContactFillTest.kt"
BE_MODEL = "backend/app/models/shipper.py"
BE_API = "backend/app/api/v1/shipper.py"
BE_BOOT = "backend/app/core/schema_bootstrap.py"
DOC = "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"

#: `applyLocation` 里那段回填（**逐字节**，删掉它 = 下单页不再带出联系人）
APPLY_LOCATION_FILL = (
    "        val c = fillReceiver(\n"
    "            ReceiverContact(dongjiaName, dongjiaPhone),\n"
    "            l.contactName,\n"
    "            l.contactPhone,\n"
    "            ContactFillMode.BROUGHT,\n"
    "        )\n"
    "        dongjiaName = c.name\n"
    "        dongjiaPhone = c.phone\n"
)

#: (说明, 相对路径, 替换函数, 期望在输出里出现的关键词 —— 空串 = 只要非零退出)
CASES: list[tuple[str, str, object, str]] = [
    (
        "① 地点编辑**不回填**联系人（改个地点名就把绑定静默清掉）",
        ADDR_VM,
        lambda s: s.replace(
            "        locContactName = l.contactName\n        locContactPhone = l.contactPhone\n", "", 1
        ),
        "回填",
    ),
    (
        "② 保存地点**不带**联系人（编辑一次 = 解绑）",
        ADDR_VM,
        lambda s: s.replace(
            "                    contactName = locContactName.trim(),\n"
            "                    contactPhone = locContactPhone.trim(),\n",
            "",
            1,
        ),
        "带进请求体",
    ),
    (
        "③ 下单页选「我的地点」不再带出联系人（这个功能的主场景没了）",
        ORDER_VM,
        lambda s: s.replace(APPLY_LOCATION_FILL, "", 1),
        "带出来",
    ),
    (
        "④ 挑人改成 BROUGHT（会拼出「名字上一位、电话这一位」的人）",
        ORDER_VM,
        lambda s: s.replace("            ContactFillMode.PICKED,\n", "            ContactFillMode.BROUGHT,\n", 1),
        "PICKED",
    ),
    (
        "⑤ **共享地点**那一支也去读联系人（往全库共用的表上绑人）",
        ORDER_VM,
        lambda s: s.replace(
            "        addressDetail = p.detailAddress.ifBlank { p.name }\n",
            "        addressDetail = p.detailAddress.ifBlank { p.name }\n"
            "        val leaked = p.contactName\n",
            1,
        ),
        "共享地点",
    ),
    (
        "⑥ 又有人把名册摊成一个下拉（同一个联系人一处挑得到、另一处挑不到）",
        ADDR_SCREEN,
        lambda s: s.replace(
            "    val snackbar = remember { SnackbarHostState() }\n",
            "    val snackbar = remember { SnackbarHostState() }\n    vm.contacts.forEach { }\n",
            1,
        ),
        "第二份",
    ),
    (
        "⑦ 回填判据被改名（判据必须报红，而不是安静地空转）",
        FILL,
        lambda s: s.replace("fun fillReceiver(", "fun fillReceiverZZZ(", 1),
        "只有一处定义",
    ),
    (
        "⑧ `LocationDto` 丢出参字段（界面永远显示「未绑定」）",
        DTOS,
        lambda s: s.replace('@SerialName("contact_name") val contactName: String = "",',
                             '@SerialName("contact_name") val contactNameZZZ: String = "",', 1),
        "LocationDto",
    ),
    (
        "⑨ `PlaceDto` 长出联系人字段（共享库不绑人这条被推翻）",
        DTOS,
        lambda s: s.replace(
            'data class PlaceDto(\n    val id: Long,\n    val name: String = "",',
            'data class PlaceDto(\n    val id: Long,\n    val name: String = "",\n    val contactName: String = "",',
            1,
        ),
        "PlaceDto",
    ),
    (
        "⑩ AI 改地点不回填（模型说一句「改个名」就把绑定清了）",
        AI_DATA,
        lambda s: s.replace(
            '                contactName = fields.str("contact_name") ?: cur.contactName,\n',
            '                contactName = fields.str("contact_name").orEmpty(),\n',
            1,
        ),
        "AI 改地点时回填",
    ),
    (
        "⑪ 后端 PATCH 丢掉 `None` 三档语义（不传也当「清空」）",
        BE_API,
        lambda s: s.replace("    if body.contact_name is not None:\n", "    if True:\n", 1),
        "三档",
    ),
    (
        "⑫ 线上补列被删掉（旧库没有这两列 → 读一地点的接口直接 500）",
        BE_BOOT,
        lambda s: s.replace(
            '            ("contact_name", "VARCHAR(128) DEFAULT \'\'"),\n'
            '            ("contact_phone", "VARCHAR(32) DEFAULT \'\'"),\n',
            "",
            1,
        ),
        "补列",
    ),
    (
        "⑬ 补列的列宽与模型不一致（MySQL 上截断/报错）",
        BE_BOOT,
        lambda s: s.replace('("contact_name", "VARCHAR(128) DEFAULT \'\'")',
                            '("contact_name", "VARCHAR(64) DEFAULT \'\'")', 1),
        "列宽",
    ),
    (
        "⑭ 模型里那两列的类型被改窄（快照串存不下 / 判据空转）",
        BE_MODEL,
        lambda s: s.replace(
            'contact_name: Mapped[str] = mapped_column(String(128), default="")',
            'contact_name: Mapped[str] = mapped_column(String(64), default="")',
            1,
        ),
        "两列",
    ),
    (
        "⑮ 回填判据的单测被改坏（一个用例都不调 `fillReceiver` 了）",
        TEST,
        lambda s: s.replace("fillReceiver(", "fillReceiverZZZ("),
        "单测",
    ),
    (
        "⑯ 设计规范那一节被删（下一个人还会各写一份）",
        DOC,
        lambda s: s.replace("ContactFill", "QtyStepper"),
        "设计规范",
    ),
    (
        "⑰ 判据清单指向不存在的文件（红线变成空转）",
        CHECK_REL,
        lambda s: s.replace('FILL = AND / "ui/common/ContactFill.kt"',
                            'FILL = AND / "ui/common/ContactFillGone.kt"', 1),
        "存在",
    ),
    (
        "⑱ 反向验证脚本自己不见了（新红线没配反向验证）",
        CHECK_REL,
        lambda s: s.replace('REVERSE = "_tools/qa/_reverse_verify_contact_binding.py"',
                            'REVERSE = "_tools/qa/_reverse_verify_contact_binding_gone.py"', 1),
        "反向验证",
    ),
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
        # 按行尾归一后再替换（Windows 上 Kotlin 文件可能是 CRLF），写回时按原样还原
        crlf = b"\r\n" in original_bytes
        plain = original_bytes.decode("utf-8").replace("\r\n", "\n")
        mutated = mutate(plain)  # type: ignore[operator]
        if mutated == plain:
            fails.append(f"{label}：注入没生效（锚点变了，请更新本脚本）")
            print(f"  [SKIP] {label}")
            continue
        try:
            out_txt = mutated.replace("\r\n", "\n")
            if crlf:
                out_txt = out_txt.replace("\n", "\r\n")
            path.write_bytes(out_txt.encode("utf-8"))
            code, out = run_check()
        finally:
            path.write_bytes(original_bytes)
        hit = code != 0 and (not expect or expect in out)
        if hit:
            print(f"  [OK] {label} → 报红")
        else:
            fails.append(f"{label}：注入之后没有按预期报红（退出码 {code}，期望关键词「{expect}」）")
            print(f"  [MISS] {label} → 仍然全绿")

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
