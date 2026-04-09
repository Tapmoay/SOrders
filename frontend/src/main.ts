import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { Lazyload } from 'vant'
import Vant from 'vant'
import 'vant/lib/index.css'
import './styles/theme-tokens.css'

import App from './App.vue'
import router from './router'
import './styles/layout.css'
import './styles/role-tool-pages.css'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(Vant)
app.use(Lazyload)
app.mount('#app')
