/**
 * 金额展示：固定两位小数（本项目的统一口径）。
 *
 * ⚠️ 参数故意收 `unknown`：后端 `Decimal` 序列化出来是**字符串**（实测 `'12.5000'`、
 * `'149.9885265700483091787439614'`），而通知 payload 是 `Record<string, unknown>` ——
 * 收窄成 `string | number` 会逼调用点写 `as` 断言（那些断言迟早会掩盖真正的类型错误）。
 * 函数内部对任何非数值输入都返回 `0.00`，不会抛。
 */
export function formatMoney2(v: unknown): string {
  if (v === null || v === undefined || v === '') return '0.00'
  const n = Number(v)
  if (Number.isNaN(n)) return '0.00'
  return n.toFixed(2)
}
