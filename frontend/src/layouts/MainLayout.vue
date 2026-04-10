<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterView, START_LOCATION, useRoute, useRouter } from 'vue-router'

import MessageCenterPopup from '@/components/MessageCenterPopup.vue'
import ShipperPriceNoticeBar from '@/components/ShipperPriceNoticeBar.vue'
import { useSocketRealtime } from '@/composables/useSocketRealtime'
import { duringAuthRecovery } from '@/api/client'
import { fetchMe } from '@/api/user'
import { useAuthStore } from '@/stores/auth'
import { useDispatcherWorkbenchStore } from '@/stores/dispatcherWorkbench'
import { useMessageCenterStore } from '@/stores/messageCenter'
import {
  dispatcherCompletedTabBadge,
  dispatcherDashboardTabBadge,
  dispatcherLedgerTabBadge,
  dispatcherPendingTabBadge,
  dispatcherPricesTabBadge,
  driverCompletedTabBadge,
  driverOpenTabBadge,
} from '@/utils/tabNotificationBadges'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const msg = useMessageCenterStore()
const dispatcherWorkbench = useDispatcherWorkbenchStore()
const recipientId = computed(() => auth.userId)

useSocketRealtime()

/** 从其他 Tab 点进「派单」后收起待派单角标；首屏直达 /dispatcher/pending 不自动消（仍可看红点） */
router.afterEach((to, from) => {
  if (auth.role !== 'dispatcher') return
  if (to.path !== '/dispatcher/pending') return
  if (from === START_LOCATION) return
  dispatcherWorkbench.acknowledgePendingPoolBadge()
})

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
    const me = await duringAuthRecovery(() => fetchMe())
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

/** 底部 Tab 角标：按消息 type 对应到各 Tab（非全局未读总数） */
const driverOpenBadge = computed(() =>
  driverOpenTabBadge(msg.items, recipientId.value, auth.role),
)
const driverCompletedBadge = computed(() =>
  driverCompletedTabBadge(msg.items, recipientId.value, auth.role),
)
/** 派单 Tab：待派单池订单数优先于消息 type 角标（后者多为空）；进入过工作台后可收起至再次出现增量 */
const dispatcherPendingBadge = computed(() => {
  const pool = dispatcherWorkbench.pendingPoolForBadge
  if (pool > 0) return pool > 99 ? '99+' : pool
  return dispatcherPendingTabBadge(msg.items, recipientId.value, auth.role)
})
const dispatcherCompletedBadge = computed(() =>
  dispatcherCompletedTabBadge(msg.items, recipientId.value, auth.role),
)
const dispatcherDashboardBadge = computed(() =>
  dispatcherDashboardTabBadge(msg.items, recipientId.value, auth.role),
)
const dispatcherPricesBadge = computed(() =>
  dispatcherPricesTabBadge(msg.items, recipientId.value, auth.role),
)
const dispatcherLedgerBadge = computed(() =>
  dispatcherLedgerTabBadge(msg.items, recipientId.value, auth.role),
)

const tabBadgeProps = { color: '#ee0a24' }

/** 当前消息列表中的未读条数（与 Tab 角标同一套 recipient 规则），用于兜底 Socket unread_count 丢失 */
const localUnreadFromItems = computed(() => {
  const id = recipientId.value
  const role = auth.role
  return msg.items.filter((n) => {
    if (n.read_at != null) return false
    if (role === 'dispatcher') {
      if (id == null) return false
      return Number(n.recipient_id) === Number(id)
    }
    if (id != null) return Number(n.recipient_id) === Number(id)
    return true
  }).length
})

/** 铃铛：未读消息优先；派单员在无站内信未读时展示待派单池数量（与 Tab 同步抑制） */
const navBellBadgeContent = computed(() => {
  const u = Math.max(msg.unreadCount, localUnreadFromItems.value)
  if (u > 0) return u > 99 ? '99+' : u
  if (auth.role === 'dispatcher' && dispatcherWorkbench.pendingPoolForBadge > 0) {
    const p = dispatcherWorkbench.pendingPoolForBadge
    return p > 99 ? '99+' : p
  }
  return ''
})

/** 货主端：顶栏深色底 + 白字 */
const shipperTopNav = computed(() => route.path.startsWith('/shipper'))

function onBack() {
  if (showBack.value) router.back()
}

function logout() {
  auth.clearSession()
  router.replace('/login')
}

/** 已在「派单」Tab 时再次点击，收起角标（无路由跳转时 afterEach 不会触发） */
function onDispatcherPendingTabClick() {
  if (auth.role !== 'dispatcher') return
  if (route.path === '/dispatcher/pending') {
    dispatcherWorkbench.acknowledgePendingPoolBadge()
  }
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
      safe-area-inset-top
      @click-left="onBack"
    >
      <template #right>
        <div class="nav-right">
          <van-badge
            :content="navBellBadgeContent"
            max="99"
            color="#ee0a24"
            :show-zero="false"
          >
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
      <van-tabbar-item
        replace
        to="/driver/open"
        icon="logistics"
        :badge="driverOpenBadge"
        :badge-props="tabBadgeProps"
      >
        未完成
      </van-tabbar-item>
      <van-tabbar-item
        replace
        to="/driver/completed"
        icon="passed"
        :badge="driverCompletedBadge"
        :badge-props="tabBadgeProps"
      >
        已完成
      </van-tabbar-item>
    </van-tabbar>
    <van-tabbar v-else-if="showDispatcherTab" route fixed placeholder safe-area-inset-bottom>
      <van-tabbar-item
        replace
        to="/dispatcher/pending"
        icon="orders-o"
        :badge="dispatcherPendingBadge"
        :badge-props="tabBadgeProps"
        @click="onDispatcherPendingTabClick"
      >
        派单
      </van-tabbar-item>
      <van-tabbar-item
        replace
        to="/dispatcher/completed"
        icon="passed"
        :badge="dispatcherCompletedBadge"
        :badge-props="tabBadgeProps"
      >
        送达
      </van-tabbar-item>
      <van-tabbar-item
        replace
        to="/dispatcher/dashboard"
        icon="bar-chart-o"
        :badge="dispatcherDashboardBadge"
        :badge-props="tabBadgeProps"
      >
        看板
      </van-tabbar-item>
      <van-tabbar-item
        replace
        to="/dispatcher/prices"
        icon="gold-coin-o"
        :badge="dispatcherPricesBadge"
        :badge-props="tabBadgeProps"
      >
        价格
      </van-tabbar-item>
      <van-tabbar-item
        replace
        to="/dispatcher/ledger"
        icon="balance-list-o"
        :badge="dispatcherLedgerBadge"
        :badge-props="tabBadgeProps"
      >
        账本
      </van-tabbar-item>
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
