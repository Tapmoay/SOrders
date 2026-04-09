/** localStorage 带过期时间的 JSON 缓存 */

const PREFIX = 'sorders_cache_'

export interface CacheEnvelope<T> {
  exp: number
  data: T
}

export function cacheGet<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(PREFIX + key)
    if (!raw) return null
    const env = JSON.parse(raw) as CacheEnvelope<T>
    if (!env || typeof env.exp !== 'number' || env.exp < Date.now()) {
      localStorage.removeItem(PREFIX + key)
      return null
    }
    return env.data
  } catch {
    return null
  }
}

export function cacheSet<T>(key: string, data: T, ttlMs: number) {
  try {
    const env: CacheEnvelope<T> = { exp: Date.now() + ttlMs, data }
    localStorage.setItem(PREFIX + key, JSON.stringify(env))
  } catch {
    /* quota */
  }
}

export function cacheRemove(key: string) {
  try {
    localStorage.removeItem(PREFIX + key)
  } catch {
    /* ignore */
  }
}
