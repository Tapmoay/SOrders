import { http } from './client'
import { cacheGet, cacheRemove, cacheSet } from '@/utils/localCache'

/** 与后端 UserRole 枚举一致 */
export type UserRole = 'shipper' | 'driver' | 'dispatcher'

export interface UserMe {
  id: number
  username: string
  phone: string
  full_name: string
  role: UserRole
  is_active: boolean
  created_at: string
}

export interface UserListItem {
  id: number
  username: string
  phone: string
  full_name: string
  role: UserRole
  is_active: boolean
  created_at: string
}

export async function fetchMe() {
  const { data } = await http.get<UserMe>('/users/me')
  return data
}

const DRIVERS_CACHE_KEY = 'users_role_driver'

export async function fetchUsers(params?: { role?: UserRole; limit?: number }, forceRefresh = false) {
  const reqLimit = params?.limit ?? 500
  const onlyDrivers = params?.role === 'driver' && reqLimit === 500
  if (onlyDrivers && !forceRefresh) {
    const hit = cacheGet<UserListItem[]>(DRIVERS_CACHE_KEY)
    if (hit?.length) return hit
  }
  const { data } = await http.get<UserListItem[]>('/users', {
    params: { ...params, limit: params?.limit ?? 500 },
  })
  const rows: UserListItem[] = Array.isArray(data) ? data : []
  const out = rows.filter((u) => u.is_active)
  if (onlyDrivers) {
    cacheSet(DRIVERS_CACHE_KEY, out, 3 * 60 * 1000)
  }
  return out
}

export function invalidateDriversCache() {
  cacheRemove(DRIVERS_CACHE_KEY)
}

export interface UserCreatePayload {
  phone: string
  username?: string | null
  password: string
  full_name?: string
  role: UserRole
}

export interface UserUpdatePayload {
  phone?: string
  password?: string
  full_name?: string
  role?: UserRole
  is_active?: boolean
}

export async function createUser(body: UserCreatePayload) {
  const { data } = await http.post<UserListItem>('/users', body)
  return data
}

export async function updateUser(userId: number, body: UserUpdatePayload) {
  const { data } = await http.patch<UserListItem>(`/users/${userId}`, body)
  return data
}
