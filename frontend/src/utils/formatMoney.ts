/**
 * 金额展示：按分四舍五入后**去掉末尾多余的 0**（本项目的统一显示口径）。
 *
 * - `56.70` → `56.7`、`87.00` → `87`、`0.50` → `0.5`（用户 2026-09-22：「有零的全省」）
 * - `56.77` → `56.77` —— 只动**末尾的 0**，绝不近似（"去掉多余的 0" ≠ "把 7 约掉"）
 *
 * ⛔ 这是**显示**口径，不是"值"：接口出参、写回后端的金额、以及任何拿来做判据的字符串
 * （如 Android 侧 `goodsTotalText()`）都保持两位小数 —— 与 App 的 `util/Money.kt::formatMoney` 同一条规则。
 *
 * ⚠️ 参数故意收 `unknown`：后端 `Decimal` 序列化出来是**字符串**（实测 `'12.5000'`、
 * `'149.9885265700483091787439614'`），而通知 payload 是 `Record<string, unknown>` ——
 * 收窄成 `string | number` 会逼调用点写 `as` 断言（那些断言迟早会掩盖真正的类型错误）。
 * 函数内部对任何非数值输入都返回 `0`，不会抛。
 */
export function formatMoney2(v: unknown): string {
  if (v === null || v === undefined || v === '') return '0'
  const n = Number(v)
  if (Number.isNaN(n)) return '0'
  // `toFixed(2)` 一定带小数点，所以先删 '0' 再删那个小数点不会误伤 `100` 这种整数。
  const s = n.toFixed(2).replace(/\.?0+$/, '')
  // `-0.001` 会印成 `-0`：负零不是钱，摆正。
  return s === '-0' ? '0' : s
}
