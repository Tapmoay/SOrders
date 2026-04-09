import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import type { UserRole } from '@/api/user'

const ROLE_KEY = 'user_role'
const USER_ID_KEY = 'user_id'

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

  return { token, role, userId, isAuthenticated, setSession, clearSession }
})
