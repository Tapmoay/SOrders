<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterView, useRoute, useRouter } from 'vue-router'

import MessageCenterPopup from '@/components/MessageCenterPopup.vue'
import ShipperPriceNoticeBar from '@/components/ShipperPriceNoticeBar.vue'
import { useSocketRealtime } from '@/composables/useSocketRealtime'
import { fetchMe } from '@/api/user'
import { useAuthStore } from '@/stores/auth'
import { useMessageCenterStore } from '@/stores/messageCenter'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const msg = useMessageCenterStore()

useSocketRealtime()

function homeForRole(role: string) {
  if (role === 'shipper') return '/shipper'
  if (role === 'driver') return '/driver/open'
  if (role === 'dispatcher') return '/dispatcher/pending'
  return '/login'
}

/** 与后端同步角色，避免 localStorage 与 JWT/账号不一致导致接口 403 */
onMounted(async () => {
  const token = auth.token
  if (!token) return
  try {
    const me = await fetchMe()
    auth.setSession(token, me.role, me.id)
    const need = route.matched.find((r) => r.meta.role)?.meta.role as string | undefined
    if (need && me.role !== need) {
      await router.replace(homeForRole(me.role))
    }
  } catch {
    /* 401 由 axios 拦截跳转登录 */
  }
})

const showMessages = ref(false)

const title = computed(() => {
  const r = [...route.matched].reverse().find((x) => x.meta.title)
  return (r?.meta.title as string | undefined) ?? '派单送货'
})

const showBack = computed(() => !route.meta.hideBack)

const showDriverTab = computed(() => Boolean(route.meta.driverTab))
const showDispatcherTab = computed(() => Boolean(route.meta.dispatcherTab))
const showBottomTabbar = computed(() => showDriverTab.value || showDispatcherTab.value)

/** 货主端：顶栏深色底 + 白字 */
const shipperTopNav = computed(() => route.path.startsWith('/shipper'))

function onBack() {
  if (showBack.value) router.back()
}

function logout() {
  auth.clearSession()
  router.replace('/login')
}
</script>

<template>
  <div
    class="app-page"
    :class="{
      'app-page--with-tabbar': showBottomTabbar,
      'app-page--shipper-nav': shipperTopNav,
      'app-page--default-nav': !shipperTopNav,
    }"
  >
    <van-nav-bar
      :title="title"
      :left-arrow="showBack"
      :border="true"
      @click-left="onBack"
    >
      <template #right>
        <div class="nav-right">
          <van-badge :content="msg.unreadCount > 0 ? msg.unreadCount : ''" max="99">
            <van-icon name="bell" size="22" @click="showMessages = true" />
          </van-badge>
          <van-button
            size="small"
            plain
            class="nav-logout-btn"
            @click="logout"
          >
            退出
          </van-button>
        </div>
      </template>
    </van-nav-bar>
    <ShipperPriceNoticeBar v-if="shipperTopNav" @open-messages="showMessages = true" />
    <RouterView />
    <MessageCenterPopup v-model:show="showMessages" />
    <van-tabbar v-if="showDriverTab" route fixed placeholder safe-area-inset-bottom>
      <van-tabbar-item replace to="/driver/open" icon="logistics">未完成</van-tabbar-item>
      <van-tabbar-item replace to="/driver/completed" icon="passed">已完成</van-tabbar-item>
    </van-tabbar>
    <van-tabbar v-else-if="showDispatcherTab" route fixed placeholder safe-area-inset-bottom>
      <van-tabbar-item replace to="/dispatcher/pending" icon="orders-o">派单</van-tabbar-item>
      <van-tabbar-item replace to="/dispatcher/completed" icon="passed">送达</van-tabbar-item>
      <van-tabbar-item replace to="/dispatcher/dashboard" icon="bar-chart-o">看板</van-tabbar-item>
      <van-tabbar-item replace to="/dispatcher/prices" icon="gold-coin-o">价格</van-tabbar-item>
      <van-tabbar-item replace to="/dispatcher/ledger" icon="balance-list-o">账本</van-tabbar-item>
    </van-tabbar>
  </div>
</template>

<style scoped>
.nav-right {
  display: flex;
  align-items: center;
  gap: 10px;
}
.app-page--with-tabbar :deep(.van-nav-bar) + * {
  padding-bottom: 56px;
}

/* 货主：克制品牌蓝顶栏（纯色，减少渐变噪音） */
.app-page--shipper-nav :deep(.van-nav-bar) {
  background: var(--van-primary-color, #1677ff);
  box-shadow: 0 1px 0 rgba(0, 0, 0, 0.06);
}
.app-page--shipper-nav :deep(.van-nav-bar__title) {
  color: #fff;
}
.app-page--shipper-nav :deep(.van-nav-bar .van-icon) {
  color: #fff;
}
.app-page--shipper-nav :deep(.van-nav-bar__arrow) {
  color: #fff;
}
.app-page--shipper-nav :deep(.van-nav-bar__content) {
  color: #fff;
}
.app-page--shipper-nav :deep(.nav-right .van-badge__wrapper) {
  color: #fff;
}
.app-page--shipper-nav :deep(.nav-logout-btn) {
  color: #fff !important;
  border-color: rgba(255, 255, 255, 0.9) !important;
  background: transparent;
}
.app-page--shipper-nav :deep(.nav-logout-btn:active) {
  opacity: 0.85;
}

/* 司机 / 派单员：白顶栏 + 清晰标题层级，避免与货主端两套强风格冲突 */
.app-page--default-nav :deep(.van-nav-bar) {
  background: var(--van-background-2);
  box-shadow: inset 0 -1px 0 var(--van-border-color);
}
.app-page--default-nav :deep(.van-nav-bar__title) {
  color: var(--van-text-color);
  font-weight: 600;
}
.app-page--default-nav :deep(.van-nav-bar .van-icon),
.app-page--default-nav :deep(.van-nav-bar__arrow) {
  color: var(--van-text-color);
}
.app-page--default-nav :deep(.nav-right .van-badge__wrapper) {
  color: var(--van-text-color);
}
.app-page--default-nav :deep(.nav-logout-btn) {
  color: var(--van-primary-color) !important;
  border-color: rgba(22, 119, 255, 0.45) !important;
  background: transparent;
}
.app-page--default-nav :deep(.nav-logout-btn:active) {
  opacity: 0.88;
}
</style>
