<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { showFailToast, showSuccessToast } from 'vant'

import { login, register, sendRegisterSms } from '@/api/auth'
import { fetchMe } from '@/api/user'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()

const loginName = ref('')
const password = ref('')

const regUsername = ref('')
const regMobile = ref('')
const verifyCode = ref('')

const mode = ref<'login' | 'register'>('login')
const loading = ref(false)
/** 密码框显示/隐藏（登录与注册共用一条密码） */
const showPassword = ref(false)
const smsCooldown = ref(0)
let smsTimer: ReturnType<typeof setInterval> | null = null

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

watch(mode, (m) => {
  if (m === 'login') {
    regUsername.value = ''
    regMobile.value = ''
    verifyCode.value = ''
  } else {
    loginName.value = ''
  }
})

function homePath(role: string) {
  if (role === 'shipper') return '/shipper'
  if (role === 'driver') return '/driver/open'
  if (role === 'dispatcher') return '/dispatcher/pending'
  return '/login'
}

async function onSendSms() {
  const p = regMobile.value.trim()
  if (!/^1[3-9]\d{9}$/.test(p)) {
    showFailToast('请输入正确的手机号')
    return
  }
  if (smsCooldown.value > 0) return
  try {
    const res = await sendRegisterSms(p)
    showSuccessToast('验证码已发送')
    if (import.meta.env.DEV && res.code) {
      console.info('[dev] SMS code:', res.code)
    }
    smsCooldown.value = 60
    smsTimer = setInterval(() => {
      smsCooldown.value -= 1
      if (smsCooldown.value <= 0 && smsTimer) {
        clearInterval(smsTimer)
        smsTimer = null
      }
    }, 1000)
  } catch (e: unknown) {
    showFailToast(formatRequestError(e))
  }
}

async function onSubmit() {
  loading.value = true
  try {
    if (mode.value === 'login') {
      const tok = await login({ phone: loginName.value.trim(), password: password.value })
      localStorage.setItem('access_token', tok.access_token)
      auth.setSession(tok.access_token, tok.role, tok.user_id)
      const me = await fetchMe()
      auth.setSession(tok.access_token, me.role, me.id)
      showSuccessToast('登录成功')
      router.replace(homePath(me.role))
    } else {
      const tok = await register({
        username: regUsername.value.trim(),
        password: password.value,
        phone: regMobile.value.trim(),
        verification_code: verifyCode.value.trim(),
      })
      localStorage.setItem('access_token', tok.access_token)
      auth.setSession(tok.access_token, tok.role, tok.user_id)
      const me = await fetchMe()
      auth.setSession(tok.access_token, me.role, me.id)
      showSuccessToast('注册成功')
      router.replace(homePath(me.role))
    }
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
        <p class="hint">使用用户名与密码登录或注册；登录成功后进入对应工作台。</p>

        <div class="mode-seg" role="tablist" aria-label="登录或注册">
          <button
            type="button"
            class="mode-seg__btn"
            :class="{ 'mode-seg__btn--active': mode === 'login' }"
            role="tab"
            :aria-selected="mode === 'login'"
            @click="mode = 'login'"
          >
            登录
          </button>
          <button
            type="button"
            class="mode-seg__btn"
            :class="{ 'mode-seg__btn--active': mode === 'register' }"
            role="tab"
            :aria-selected="mode === 'register'"
            @click="mode = 'register'"
          >
            注册
          </button>
        </div>

        <van-form @submit="onSubmit">
          <van-cell-group inset>
            <template v-if="mode === 'login'">
              <van-field
                v-model="loginName"
                name="loginName"
                label="用户名"
                type="text"
                maxlength="32"
                autocomplete="username"
                placeholder="用户名或手机号"
                :rules="[{ required: true, message: '请填写用户名' }]"
              />
              <van-field
                v-model="password"
                :type="showPassword ? 'text' : 'password'"
                name="password"
                label="密码"
                placeholder="密码"
                autocomplete="current-password"
                :rules="[{ required: true, message: '请填写密码' }]"
              >
                <template #right-icon>
                  <van-icon
                    :name="showPassword ? 'eye-o' : 'closed-eye'"
                    class="pwd-eye"
                    @click.stop="showPassword = !showPassword"
                  />
                </template>
              </van-field>
            </template>
            <template v-else>
              <van-field
                v-model="regUsername"
                name="regUsername"
                label="用户名"
                type="text"
                maxlength="32"
                autocomplete="username"
                placeholder="设置登录用户名"
                :rules="[{ required: true, message: '请填写用户名' }]"
              />
              <van-field
                v-model="password"
                :type="showPassword ? 'text' : 'password'"
                name="password"
                label="密码"
                placeholder="密码"
                autocomplete="new-password"
                :rules="[{ required: true, message: '请填写密码' }]"
              >
                <template #right-icon>
                  <van-icon
                    :name="showPassword ? 'eye-o' : 'closed-eye'"
                    class="pwd-eye"
                    @click.stop="showPassword = !showPassword"
                  />
                </template>
              </van-field>
              <van-field
                v-model="regMobile"
                name="mobile"
                label="手机号"
                type="tel"
                maxlength="11"
                placeholder="11 位手机号"
                :rules="[{ required: true, message: '请填写手机号' }]"
              >
                <template #button>
                  <van-button
                    size="small"
                    type="primary"
                    plain
                    :disabled="smsCooldown > 0"
                    native-type="button"
                    @click="onSendSms"
                  >
                    {{ smsCooldown > 0 ? `${smsCooldown}s` : '获取验证码' }}
                  </van-button>
                </template>
              </van-field>
              <van-field
                v-model="verifyCode"
                name="verifyCode"
                label="验证码"
                type="digit"
                maxlength="8"
                placeholder="短信验证码"
                :rules="[{ required: true, message: '请填写验证码' }]"
              />
            </template>
          </van-cell-group>

          <p v-if="mode === 'register'" class="register-tip">司机与派单员账号由管理员开通。</p>

          <div class="actions">
            <van-button round block type="primary" native-type="submit" :loading="loading">
              {{ mode === 'login' ? '登录' : '注册' }}
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

.register-tip {
  margin: 12px 16px 0;
  font-size: 12px;
  color: var(--van-text-color-3);
  line-height: 1.5;
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
