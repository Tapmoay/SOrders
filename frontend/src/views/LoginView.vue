<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { showFailToast, showSuccessToast } from 'vant'

import { login } from '@/api/auth'
import { fetchMe } from '@/api/user'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()

const loginName = ref('')
const password = ref('')

const loading = ref(false)
const showPassword = ref(false)

/** 兼容旧版后端或未重启实例返回的英文 detail */
const EN_TO_ZH: Record<string, string> = {
  'invalid credentials': '用户名或密码错误',
  'could not validate credentials': '登录已失效或凭证无效，请重新登录',
  'not found': '未找到对应记录',
  forbidden: '无权访问',
  'permission denied': '无操作权限',
}

function normalizeApiMessage(raw: string): string {
  const z = EN_TO_ZH[raw.trim().toLowerCase()]
  return z ?? raw
}

function formatRequestError(e: unknown): string {
  const err = e as {
    message?: string
    code?: string
    response?: { status?: number; data?: { detail?: unknown } }
  }
  if (!err.response) {
    if (err.code === 'ERR_NETWORK' || err.message === 'Network Error') {
      return '无法连接后端：请确认 API 已启动（默认 http://127.0.0.1:8000），且前端通过 Vite 开发服务访问以便代理 /api'
    }
    return err.message || '网络异常'
  }
  const d = err.response.data?.detail
  if (typeof d === 'string') return normalizeApiMessage(d)
  if (Array.isArray(d)) {
    return d
      .map((x: { msg?: string } | string) =>
        typeof x === 'string' ? normalizeApiMessage(x) : normalizeApiMessage(x.msg ?? JSON.stringify(x)),
      )
      .join('；')
  }
  if (d != null && typeof d === 'object') return JSON.stringify(d)
  return `请求失败（${err.response.status ?? '?'}）`
}

function applySavedLoginPrefill() {
  const c = auth.getSavedLoginCredentials()
  if (c) {
    loginName.value = c.loginId
    password.value = c.password
  }
}

/** 首次点击/聚焦登录输入框时：清空界面上的用户名与密码，并删除本地保存的凭据 */
let loginFieldInteractCleared = false
function onLoginFieldInteract() {
  if (loginFieldInteractCleared) return
  loginFieldInteractCleared = true
  loginName.value = ''
  password.value = ''
  auth.clearAutoLoginCredentials()
}

onMounted(() => {
  loginFieldInteractCleared = false
  applySavedLoginPrefill()
})

function homePath(role: string) {
  if (role === 'shipper') return '/shipper'
  if (role === 'driver') return '/driver/open'
  if (role === 'dispatcher') return '/dispatcher/pending'
  return '/login'
}

async function onSubmit() {
  loading.value = true
  try {
    const id = loginName.value.trim()
    const pwd = password.value
    const tok = await login({ phone: id, password: pwd })
    auth.setSession(tok.access_token, tok.role, tok.user_id)
    const me = await fetchMe()
    auth.setSession(tok.access_token, me.role, me.id)
    auth.persistAutoLogin(id, pwd)
    showSuccessToast('登录成功')
    router.replace(homePath(me.role))
  } catch (e: unknown) {
    showFailToast(formatRequestError(e))
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-wrap">
    <div class="app-page login-page">
      <van-nav-bar title="派单送货" class="login-nav-bar" />

      <div class="pad">
        <p class="hint">使用用户名与密码登录；账号由管理员开通，登录成功后进入对应工作台。</p>

        <van-form @submit="onSubmit">
          <van-cell-group inset>
            <van-field
              v-model="loginName"
              name="loginName"
              label="用户名"
              type="text"
              maxlength="32"
              autocomplete="username"
              placeholder="用户名或手机号"
              :rules="[{ required: true, message: '请填写用户名' }]"
              @focus="onLoginFieldInteract"
              @click="onLoginFieldInteract"
            />
            <van-field
              v-model="password"
              :type="showPassword ? 'text' : 'password'"
              name="password"
              label="密码"
              placeholder="密码"
              autocomplete="current-password"
              :rules="[{ required: true, message: '请填写密码' }]"
              @focus="onLoginFieldInteract"
              @click="onLoginFieldInteract"
            >
              <template #right-icon>
                <van-icon
                  :name="showPassword ? 'eye-o' : 'closed-eye'"
                  class="pwd-eye"
                  @click.stop="showPassword = !showPassword"
                />
              </template>
            </van-field>
          </van-cell-group>

          <div class="actions">
            <van-button round block type="primary" native-type="submit" :loading="loading">
              登录
            </van-button>
          </div>
        </van-form>
      </div>
    </div>
  </div>
</template>

<style scoped>
.login-wrap {
  min-height: 100vh;
  min-height: 100dvh;
  display: flex;
  flex-direction: column;
  background: var(--van-background);
}

.login-page {
  flex: 1;
  width: 100%;
  max-width: 480px;
  margin: 0 auto;
  padding-bottom: max(24px, env(safe-area-inset-bottom));
  box-sizing: border-box;
}

.pad {
  padding: 8px 0 0;
}

.login-nav-bar {
  background: var(--van-background-2) !important;
}

.login-nav-bar :deep(.van-nav-bar__title) {
  color: var(--van-text-color);
  font-weight: 600;
}

.hint {
  margin: 12px 16px 4px;
  font-size: 14px;
  color: var(--van-text-color-2);
  line-height: 1.55;
}

/* 分段控件：单强调色，无两颗主按钮互抢视觉 */
.mode-seg {
  display: flex;
  margin: 16px 16px 12px;
  padding: 4px;
  background: var(--van-active-color);
  border-radius: var(--van-radius-md, 10px);
  gap: 4px;
}

.mode-seg__btn {
  flex: 1;
  border: none;
  padding: 10px 12px;
  border-radius: 8px;
  font-size: 15px;
  font-weight: 500;
  line-height: 1.3;
  background: transparent;
  color: var(--van-text-color-2);
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
  transition: background-color 0.18s ease, color 0.18s ease, box-shadow 0.18s ease;
}

.mode-seg__btn--active {
  background: var(--van-background-2);
  color: var(--van-primary-color);
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.08);
}

.mode-seg__btn:focus-visible {
  outline: 2px solid var(--van-primary-color);
  outline-offset: 2px;
}

.actions {
  margin: 20px 16px 0;
}

.pwd-eye {
  font-size: 20px;
  color: var(--van-gray-6);
  padding: 4px;
  display: flex;
  align-items: center;
}
</style>
