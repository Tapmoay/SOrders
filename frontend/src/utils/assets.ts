/**
 * 将后端返回的 /static/uploads/... 转为可请求的绝对地址。
 * 相对路径始终用「当前页面 origin」，保证开发环境走 Vite 对 /static 的代理，避免指错主机导致图片不显示。
 */
export function resolveStaticUrl(path: string | null | undefined): string {
  if (!path || !String(path).trim()) return ''
  const raw = String(path).trim()
  if (raw.startsWith('http://') || raw.startsWith('https://')) return raw
  if (typeof window === 'undefined') return raw.startsWith('/') ? raw : `/${raw}`
  const normalized = raw.startsWith('/') ? raw : `/${raw}`
  return `${window.location.origin}${normalized}`
}
