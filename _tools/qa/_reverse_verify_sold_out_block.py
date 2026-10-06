# -*- coding: utf-8 -*-
"""反向验证「沽清（下架）的商品真的不能卖」这条红线**真的会红**（L-35 / BUG-0017）。

## 为什么这条要反向验证
它的判据几乎全是"某个文件里必须出现某个零件 / 某句话"，这类判据有三种典型失效方式，
每一种都必须被单独证明会红：

1. **判据变成空转**：零件被改名 / 搬走之后，判据会安静地全绿 —— 这里拿"谓词被改名 /
   文案被改成别的说法"来试（**0 处也红**）。
2. **只认"有那道闸"、不认"闸门在哪一层 / 在谁之前"**：`if not prod.is_active:` 还在，
   但被 dedent 出了 `if pid is not None:` 那一层（手输的自定义商品也一起被拒），
   或者被挪到成本快照之后 —— 这两样在界面上、在单件商品的正常下单上都看不出来。
3. **只挡界面、不挡服务端**：客户端灰了、拦了，服务端那道闸被注释掉 —— AI 下单、老包、
   直接打接口全都照下不误，而用户的单件商品测试永远是绿的。

另外几条打客户端这一侧：加号照点不误、加号只是变灰但没 enabled=false、整卡不变灰，
以及**判据自己的 REVERSE 常量指向的那份脚本**（自指）。

⚠️ 快照 / 还原按**字节**做，跑完逐字节核对（本项目栽过"注入把 bug 留在源码里"）。

用法：python _tools/qa/_reverse_verify_sold_out_block.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_sold_out_block.py"

#: Windows 上 Kotlin / Python 文件可能是 CRLF：按字节快照、归一后再替换、写回时按原样还原
CR = bytes((13,))
LF = bytes((10,))
CRLF = CR + LF

PICKER = "android/app/src/main/java/com/tapmoay/sorders/ui/common/ProductPicker.kt"
VM = "android/app/src/main/java/com/tapmoay/sorders/ui/shipper/OrderCreateViewModel.kt"
TEST_KT = "android/app/src/test/java/com/tapmoay/sorders/ui/shipper/ProductPickerTest.kt"
LIST = "android/app/src/main/java/com/tapmoay/sorders/ui/common/ProductCheckList.kt"
AI_MD = "android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteMasterData.kt"
FLOW = "backend/app/services/order_flow.py"

#: (说明, 相对路径, 替换函数, 期望在输出里出现的关键词 —— 空串 = 只要非零退出)
CASES: list[tuple[str, str, object, str]] = [
    (
        "① 选品页：加号改回照点不误（onClick = { onAdd() }，P29/L-35 原样复发）",
        PICKER,
        lambda s: s.replace(
            "onClick = { if (!soldOut) onAdd() },",
            "onClick = { onAdd() },",
            1,
        ),
        "加号：onClick 里自己再拦一道",
    ),
    (
        "② 选品页：加号只是变灰、并没有真的点不动（enabled 拿掉）",
        PICKER,
        lambda s: s.replace("enabled = !soldOut,", "enabled = true,", 1),
        "加号：enabled = !soldOut",
    ),
    (
        "③ 选品页：整卡不再变灰（只看颜色，用户看不出这件已经不能卖）",
        PICKER,
        lambda s: s.replace(
            "modifier = Modifier.padding(10.dp).alpha(if (soldOut) 0.6f else 1f),",
            "modifier = Modifier.padding(10.dp),",
            1,
        ),
        "整卡变灰",
    ),
    (
        "④ 提交页：谓词又被内联回 submit（顶层纯函数还在，但没人调它了）",
        VM,
        lambda s: s.replace(
            "val soldOut = soldOutLine(lines, products)",
            "val soldOut = lines.firstOrNull { ln -> ln.productId != null }",
            1,
        ),
        "submit 里只调那一个函数",
    ),
    (
        "⑤ 提交页：驳回的话改了口径（不再说是哪一件、也不说怎么脱身）",
        VM,
        lambda s: s.replace(
            "「${soldOut.name}」已经沽清（下架），不能再下单，先删掉这一行再提交",
            "「${soldOut.name}」这件商品不能下单，请先删掉这一行再提交",
            1,
        ),
        "拦住时指认的是哪一件",
    ),
    (
        "⑥ 服务端：那道闸被短路掉（界面拦得住，AI / 老包 / 直连接口照下不误）",
        FLOW,
        lambda s: s.replace(
            "            if not prod.is_active:",
            "            if False:  # 先不拦，客户端那边拦了",
            1,
        ),
        "服务端在 build_order_products 里判了在售",
    ),
    (
        "⑦ 服务端：判了但只记一条日志，不拒（等于没拦，单件商品照样变成订单行）",
        FLOW,
        lambda s: s.replace(
            "                raise ValueError(\n"
            "                    f\"第 {idx + 1} 行的商品「{prod.name}」已经沽清（下架），不能再下单。\"\n"
            "                    \"请先删掉这一行，或者换一件还在售的商品。\"\n"
            "                )",
            "                _ = prod.name  # 只记一下，先不拒",
            1,
        ),
        "判定之后立刻 raise ValueError",
    ),
    (
        "⑧ 服务端：闸门被 dedent 出「商品库里有这件商品」那一层（手输的自定义商品也一起被拒）",
        FLOW,
        lambda s: s.replace(
            "            if not prod.is_active:",
            "        if not prod.is_active:  # 挪出 pid 那一层",
            1,
        ),
        "三道判定都在",
    ),
    (
        "⑨ 服务端：成本快照挪到闸门之前（沽清的行先定格一个成本，再被拒）",
        FLOW,
        lambda s: s.replace(
            "            if not prod.is_active:",
            '            cost_snap = prod.cost_price or Decimal("0")\n'
            "            if not prod.is_active:",
            1,
        ),
        "成本快照仍然在闸门之后定格",
    ),
    (
        "⑩ 可见范围 / 授权页：勾选闸被拿掉（下架商品连授权都勾不动了 —— 这次修的是下单，不是授权）",
        LIST,
        lambda s: s.replace(
            ".clickable(enabled = !locked) { onToggleProduct(p.id) }",
            ".clickable(enabled = true) { onToggleProduct(p.id) }",
            1,
        ),
        "仍可勾",
    ),
    (
        "⑪ AI 写工具：那句「下架」的说明改回「系统不会拦住拿它下单」"
        "（行为改了、说法没改 = 用户照旧被这句骗）",
        AI_MD,
        lambda s: s.replace(
            "拿它下单会被拦住（服务端同样拒）；已有的单不受影响。",
            "系统不会拦住拿它下单；已有的单不受影响。",
            1,
        ),
        "AI 写工具的「下架」说法跟着行为一起改了",
    ),
    (
        "⑫ 客户端单测：不再盯着这个谓词（回头把闸门删了也没人报红）",
        TEST_KT,
        lambda s: s.replace("soldOutLine(", "soldOutLineOld(", 1),
        "客户端单测盯着这个谓词",
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
        crlf = CRLF in original_bytes
        plain = original_bytes.decode("utf-8").replace(CRLF.decode(), LF.decode())
        mutated = mutate(plain)  # type: ignore[operator]
        if mutated == plain:
            fails.append(f"{label}：注入没生效（锚点变了，请更新本脚本）")
            print(f"  [SKIP] {label}")
            continue
        try:
            out_txt = mutated
            if crlf:
                out_txt = out_txt.replace(LF.decode(), CRLF.decode())
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
