import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { Lazyload } from 'vant'
import Vant from 'vant'
import 'vant/lib/index.css'
import './styles/theme-tokens.css'
import './styles/mobile-base.css'

import App from './App.vue'
import router from './router'
import { markAppReadyForStrict401 } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import './styles/layout.css'
import './styles/role-tool-pages.css'

async function bootstrap() {
  const app = createApp(App)
  app.use(createPinia())
  const auth = useAuthStore()
  await auth.restoreSession()
  await auth.ensureRoleHydrated()
  app.use(router)
  app.use(Vant)
  app.use(Lazyload)
  app.mount('#app')
  /** 首屏子组件会并发拉消息等接口；宽限期内 401 不清会话，避免连续刷新被误踢到登录页 */
  window.setTimeout(() => markAppReadyForStrict401(), 1800)
}

void bootstrap()
