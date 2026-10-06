package com.tapmoay.sorders.ui.common

import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.input.TextFieldValue

/**
 * 「聚焦即全选」—— **数量类输入框唯一共用的一份**（2026-10-06，用户报的那一条）。
 *
 * ## 用户原话（对着「添加商品」的数量框）
 * > 「添加商品的时候……那里**就不要填 1 了，就默认是 0**」「如果他自己已经填好了 1 的话……
 * >  我们又填 15 的话，那就变成了 **115**，这就**显示了错误**了」
 * > 「**假如它没有去改的话就是 1；如果它去改的话，就是 0**，它按它填的数额去计算。是这样子的，这是个 bug」
 *
 * ## 根因
 * 数量框里放着上一次那个数（`1`），点进去**光标落在末尾**：用户想填 15，敲 `1` `5`，
 * 框里就成了 `115`。三个数量框全这样（选品 / 下单行的 `QtyStepper` ／ 账本「记一笔账」／ 采购单行数量）。
 *
 * ## 为什么选「聚焦即全选」，而不是「默认填 0」
 * 用户那两句其实给了两条路，这里选了第一条：
 * 1. 「没去改的话就是 1」—— **默认值不动**就满足；他要的是"点进去就能直接改成自己要填的数"。
 * 2. 「默认 0」与本仓库的既有裁定冲突：`QtyStepper.kt` 的 `QTY_MIN = 1` 与
 *    「0 件应该走『移除』而不是数量 0」「数量框永远显示一个合法的数」是同一条裁定；
 *    何况 `InputRules.intInput` **不去前导 0**，框里放 `0` 再敲 `15` 会显示 `015`（值没错、显示丑）。
 * 所以：**点进去 ＝ 整串选中，打字就是替换**。默认值、上下限、`typedQty` 判据一个字没动。
 *
 * ## 谁在用（只有这一处定义）
 * - `QtyStepper.kt` 里那个数量框（选品页 / 下单页行编辑 / 转单，三个调用点共用）；
 * - `Components.kt::SoTextField` 与 `FormRows.kt::FormInputRow` 各带一个**默认关闭**的
 *   `selectAllOnFocus` 开关，只有数量类字段打开（账本数量 / 采购单行数量）——
 *   其余几十个普通字段的行为**一个字都不变**。
 *
 * ⛔ 别把这段逻辑再抄一份到别的字段里：红线 `_tools/qa/_check_qty_focus_select.py` 钉着
 * 「只有一份」，反向验证 `_tools/qa/_reverse_verify_qty_focus_select.py` 逐条注入
 * （含"把全选去掉""聚焦改到每次点击"）。纯函数有 JVM 单测 `FieldSelectionTest`。
 */

/** 整串选中：打字即替换（选中区 `0..length`，光标在末尾）。纯函数，有单测。 */
fun selectedAll(v: TextFieldValue): TextFieldValue =
    v.copy(selection = TextRange(0, v.text.length))

/**
 * 从外面回填一整串值：**光标放末尾**。
 *
 * 光标若落在中间或开头，下一次打字会把光标处那几个字符顶掉 —— 与本次修的是同一类毛病。
 * 纯函数，有单测。
 */
fun fieldAtEnd(text: String): TextFieldValue =
    TextFieldValue(text, selection = TextRange(text.length))

/**
 * 聚焦即全选（挂在字段自己的 `modifier` 上；`enabled = false` 时**原样返回**，一个字不加）。
 *
 * 为什么是"聚焦那一刻"而不是"每次点击"：已经聚焦的框里再点一下**不该**再全选 ——
 * 用户要挪光标仍然挪得动（这是这次改动的逃生门）。
 */
fun Modifier.selectAllOnFocus(
    enabled: Boolean = true,
    onSelectAll: () -> Unit,
): Modifier =
    if (!enabled) this
    else onFocusChanged { state -> if (state.isFocused) onSelectAll() }
