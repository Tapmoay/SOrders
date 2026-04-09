/** 金额展示：固定两位小数 */
export function formatMoney2(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === '') return '0.00'
  const n = Number(v)
  if (Number.isNaN(n)) return '0.00'
  return n.toFixed(2)
}
