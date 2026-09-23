"""把一行写进 xlsx，并**强制字符串是文本节点**（以 `=` 开头的值不许变成活公式）。

## 为什么这是一个独立模块（2026-09-24 第 20 轮并行渗透 D7-1）
这个防护最初只写在 `services/ledger_export.py` 里（账本导出那条路），
而 `api/v1/reports.py` 的**六个 kind**（营业/商品/司机/客户/资金/审计）与
`services/stats_export.py`（看板导出）全部是裸 `ws.append(...)` ——
于是同一条规矩在同一个仓库里"一份实现了、另外两份没抄"。

### 缺陷现场（2026-09-19 第二轮外部检查 R2-1 + 2026-09-24 D7-1）
openpyxl 把"以 `=` 开头的字符串"写成**公式节点**。本机实测（读产物里的
`xl/worksheets/sheet1.xml`，不是看对象属性）：

| 写法 | 产物里的节点 |
| --- | --- |
| `ws.append(["=1+1"])` | `<c r="A1"><f>1+1</f><v></v></c>` ← **活公式** |
| 强制 `data_type='s'` 后同一个值 | `<c r="A1" t="inlineStr"><is><t>=1+1</t></is></c>` ← 文本 |

用户可控的格子有：货主名、**订单说明**（货主下单时自己填）、商品名、订单号、备注、
**开销/账本明细的 `change_content`**。任何一处以 `=` 开头（例如
`=HYPERLINK("http://…"&B1,"点我")`），导出的 xlsx 在别人的 Excel 里就是公式，打开即求值。

### 为什么用"强制类型"而不是"加前导 `'` 或空格"
前导引号/空格是 CSV 的业界做法，代价是**改动了数据本身**。xlsx 的类型是显式的，
设一次 `data_type='s'` 就能既不执行公式、又**一字不改**原值 ——
逐字节对比过改前/改后的产物，唯一变化的格子就是 `=` 开头的那些。

⚠️ 只对 `str` 生效：数量/单价/总价是**真数值列**，必须继续能被 Excel 求和。
⚠️ 所有导出都该走它：`ws.append(...)` 里只要**可能**出现用户文本，就必须过这里。
"""

from __future__ import annotations


def append_text_row(ws, cells: list) -> None:
    """写一行；字符串一律强制成文本节点（数值/日期/None 原样，仍可被 Excel 求和）。"""
    ws.append(cells)
    for c in ws[ws.max_row]:
        if isinstance(c.value, str):
            c.data_type = "s"


__all__ = ["append_text_row"]
