import type { AxiosError } from 'axios'

/** 兼容英文 detail / 系统 errno 文案，与 LoginView 的 EN_TO_ZH 对齐 */
function normalizeDetailString(detail: string, status?: number): string {
  const t = detail.trim()
  const low = t.toLowerCase()
  if (low.includes('permission denied')) {
    if (status === 403) return '无操作权限（请确认账号角色或重新登录）'
    if (status === 401) return '未登录或登录已过期'
    return '文件保存失败（服务器无法写入目录，请检查 uploads 是否可写）'
  }
  const exact: Record<string, string> = {
    forbidden: '无权访问',
    'not authenticated': '未登录或登录已过期',
    'could not validate credentials': '登录已失效或凭证无效，请重新登录',
  }
  if (low === 'not found' && status === 404) {
    return '接口不存在（404）。请确认：① 后端已部署含「账本同步」的版本；② 环境变量 VITE_API_BASE_URL 为完整 API 根路径且以 /api/v1 结尾（勿只填域名）。'
  }
  return exact[low] ?? t
}

/** 解析 FastAPI 的 detail（string | 校验错误数组）与网络错误，供 Toast 展示 */
export function formatApiError(e: unknown, fallback: string): string {
  const ax = e as AxiosError<{ detail?: unknown; message?: unknown }>
  const data = ax.response?.data as Record<string, unknown> | undefined
  const st = ax.response?.status
  const d = data?.detail
  if (typeof d === 'string' && d.trim()) return normalizeDetailString(d, st)
  if (Array.isArray(d) && d.length) {
    const parts = d.map((item) => {
      if (item && typeof item === 'object' && 'msg' in item) {
        const m = String((item as { msg: unknown }).msg)
        return normalizeDetailString(m, st)
      }
      return typeof item === 'string' ? normalizeDetailString(item, st) : JSON.stringify(item)
    })
    const s = parts.filter(Boolean).join('；')
    if (s) return s
  }
  if (data && typeof data.message === 'string' && data.message.trim()) {
    return normalizeDetailString(data.message.trim(), st)
  }
  if (st != null && st >= 400) {
    const hint =
      st === 401
        ? '未登录或登录已过期'
        : st === 403
          ? '无权限'
          : st === 413
            ? '请求体积过大'
            : st >= 500
              ? '服务器错误，请稍后重试'
              : `请求失败（${st}）`
    return hint
  }
  if (!ax.response && ax.message) {
    if (/network/i.test(ax.message)) {
      return '无法连接服务器，请确认网络或后端已启动'
    }
    return ax.message
  }
  return fallback
}
