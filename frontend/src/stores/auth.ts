import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { duringAuthRecovery } from '@/api/client'
import { logout as apiLogout } from '@/api/auth'
import { fetchMe, type UserRole } from '@/api/user'

const ROLE_KEY = 'user_role'
const USER_ID_KEY = 'user_id'
/** 与 /auth/login 的 phone 字段一致：用户名或手机号 */
const AUTO_LOGIN_ID_KEY = 'sorders_auto_login_id'
const AUTO_LOGIN_PASSWORD_KEY = 'sorders_auto_login_password'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(localStorage.getItem('access_token'))
  const role = ref<UserRole | null>((localStorage.getItem(ROLE_KEY) as UserRole | null) ?? null)
  const userId = ref<number | null>(
    localStorage.getItem(USER_ID_KEY) ? Number(localStorage.getItem(USER_ID_KEY)) : null,
  )

  const isAuthenticated = computed(() => Boolean(token.value))

  function setSession(accessToken: string, userRole: UserRole, uid?: number) {
    token.value = accessToken
    role.value = userRole
    localStorage.setItem('access_token', accessToken)
    localStorage.setItem(ROLE_KEY, userRole)
    if (uid != null && !Number.isNaN(uid)) {
      userId.value = uid
      localStorage.setItem(USER_ID_KEY, String(uid))
    }
  }

  function clearSession() {
    token.value = null
    role.value = null
    userId.value = null
    localStorage.removeItem('access_token')
    localStorage.removeItem(ROLE_KEY)
    localStorage.removeItem(USER_ID_KEY)
  }

  /**
   * 退出登录：**先让服务端作废令牌**，再清本机。
   *
   * ⚠️ 2026-09-19 审计：原来只调 `clearSession()`（删本机 localStorage），
   * 服务端令牌照样有效满 24 小时——手机丢了、在别人电脑上登过，都没有止损手段。
   * 网络失败也要把本机清干净（否则用户"退不出去"），但要把这件事如实说出来：
   * 服务端没作废成功时提示用户改密码，而不是假装已经退出。
   */
  async function logout(): Promise<{ serverRevoked: boolean }> {
    let serverRevoked = false
    try {
      await apiLogout()
      serverRevoked = true
    } catch {
      serverRevoked = false
    }
    clearSession()
    return { serverRevoked }
  }

  /**
   * 登录/注册成功后保存账号密码，用于登录页预填（不用于启动时自动请求登录）。
   * 注意：密码存于 localStorage，仅适用于可信设备。
   */
  function persistAutoLogin(loginId: string, password: string) {
    const id = loginId.trim()
    if (!id || !password) return
    try {
      localStorage.setItem(AUTO_LOGIN_ID_KEY, id)
      localStorage.setItem(AUTO_LOGIN_PASSWORD_KEY, password)
    } catch {
      /* quota / 隐私模式 */
    }
  }

  function readSavedCredentials(): { loginId: string; password: string } | null {
    try {
      const loginId = localStorage.getItem(AUTO_LOGIN_ID_KEY)?.trim()
      const password = localStorage.getItem(AUTO_LOGIN_PASSWORD_KEY)
      if (!loginId || !password) return null
      return { loginId, password }
    } catch {
      return null
    }
  }

  /** 供登录页预填；与 readSavedCredentials 相同，对外语义更清晰 */
  function getSavedLoginCredentials(): { loginId: string; password: string } | null {
    return readSavedCredentials()
  }

  /** 用户主动编辑登录输入框时调用，清除已保存的账号密码 */
  function clearAutoLoginCredentials() {
    try {
      localStorage.removeItem(AUTO_LOGIN_ID_KEY)
      localStorage.removeItem(AUTO_LOGIN_PASSWORD_KEY)
    } catch {
      /* ignore */
    }
  }

  /**
   * 启动时仅校验 JWT；不根据已保存的账号密码自动调用登录接口（需用户在登录页点击登录）。
   */
  async function restoreSession(): Promise<void> {
    const t = localStorage.getItem('access_token')?.trim()
    if (t) {
      token.value = t
      role.value = (localStorage.getItem(ROLE_KEY) as UserRole | null) ?? null
      const uidRaw = localStorage.getItem(USER_ID_KEY)
      userId.value = uidRaw && !Number.isNaN(Number(uidRaw)) ? Number(uidRaw) : null
      try {
        const me = await duringAuthRecovery(() => fetchMe())
        setSession(t, me.role, me.id)
        return
      } catch (e: unknown) {
        const status = (e as { response?: { status?: number } }).response?.status
        if (status === 401) {
          clearSession()
        } else {
          return
        }
      }
    } else {
      token.value = null
      role.value = null
      userId.value = null
    }
  }

  /**
   * 仅有 token 但缺少 role（例如 localStorage 未写入 user_role、或上次网络失败）时补拉 /users/me，
   * 避免路由因「有 token、无 role」被误判到登录页。
   */
  async function ensureRoleHydrated(): Promise<void> {
    const t = localStorage.getItem('access_token')?.trim()
    if (!t) return
    if (role.value) return
    try {
      const me = await duringAuthRecovery(() => fetchMe())
      setSession(t, me.role, me.id)
    } catch (e: unknown) {
      const status = (e as { response?: { status?: number } }).response?.status
      if (status === 401) {
        clearSession()
      }
    }
  }

  return {
    token,
    role,
    userId,
    isAuthenticated,
    setSession,
    clearSession,
    logout,
    persistAutoLogin,
    getSavedLoginCredentials,
    clearAutoLoginCredentials,
    restoreSession,
    ensureRoleHydrated,
  }
})
