import axios from 'axios'

/** 生产环境常误配为 https://host（缺 /api/v1），会导致 404 Not Found */
function normalizeApiBase(raw: string | undefined): string {
  const fallback = '/api/v1'
  let s = (raw ?? fallback).trim()
  if (!s) return fallback
  s = s.replace(/\/+$/, '')
  if (s.startsWith('/')) {
    return s || fallback
  }
  if (/^https?:\/\//i.test(s)) {
    if (/\/api\/v\d+$/i.test(s)) {
      return s
    }
    if (import.meta.env.DEV) {
      console.warn(
        '[SOrders] VITE_API_BASE_URL 应为 API 根路径，须含 /api/v1，已自动追加。',
      )
    }
    return `${s}/api/v1`
  }
  return s
}

const baseURL = normalizeApiBase(import.meta.env.VITE_API_BASE_URL)

export const http = axios.create({
  baseURL,
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

/** 启动时 restoreSession 校验 token 期间：401 不清理 localStorage、不整页跳登录 */
let authRecovery401Depth = 0

/**
 * 首屏挂载后一段时间内仍为 false，避免连续刷新时并行请求（消息、Socket 等）偶发 401
 * 触发全局清 token + 整页跳登录。超时后再启用严格 401 处理。
 */
let appReadyForStrict401 = false

export function markAppReadyForStrict401() {
  appReadyForStrict401 = true
}

export function duringAuthRecovery<T>(fn: () => Promise<T>): Promise<T> {
  authRecovery401Depth += 1
  return Promise.resolve()
    .then(fn)
    .finally(() => {
      authRecovery401Depth -= 1
    })
}

http.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  if (config.data instanceof FormData && config.headers.delete) {
    config.headers.delete('Content-Type')
  }
  return config
})

http.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      if (authRecovery401Depth > 0) {
        return Promise.reject(err)
      }
      if (!appReadyForStrict401) {
        return Promise.reject(err)
      }
      localStorage.removeItem('access_token')
      localStorage.removeItem('user_role')
      localStorage.removeItem('user_id')
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = '/login'
      }
    }
    return Promise.reject(err)
  },
)
