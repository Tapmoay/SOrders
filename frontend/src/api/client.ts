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
