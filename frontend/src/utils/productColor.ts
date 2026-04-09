/** 校验并统一为 #RRGGBB 大写，便于与后端一致、CSS 稳定显示 */
export function normalizeHexColor(raw: string | null | undefined): string | null {
  if (raw == null) return null
  const s = String(raw).trim()
  if (!s) return null
  if (!/^#[0-9A-Fa-f]{6}$/i.test(s)) return null
  return `#${s.slice(1).toUpperCase()}`
}

export function parseProductNameColorInput(raw: string): { ok: true; value: string | null } | { ok: false } {
  const t = raw.trim()
  if (!t) return { ok: true, value: null }
  const n = normalizeHexColor(t)
  if (!n) return { ok: false }
  return { ok: true, value: n }
}
