import { createRouter, createWebHistory } from 'vue-router'

import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      redirect: () => {
        const auth = useAuthStore()
        if (auth.isAuthenticated && auth.role) {
          return roleHome(auth.role)
        }
        return '/login'
      },
    },
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { public: true },
    },
    {
      path: '/shipper',
      component: () => import('@/layouts/MainLayout.vue'),
      meta: { role: 'shipper' },
      children: [
        {
          path: '',
          name: 'shipper-home',
          meta: { title: '货主', hideBack: true },
          component: () => import('@/views/shipper/ShipperHome.vue'),
        },
        {
          path: 'orders',
          name: 'shipper-orders',
          meta: { title: '我的订单' },
          component: () => import('@/views/shipper/OrderList.vue'),
        },
        {
          path: 'orders/create',
          name: 'shipper-order-create',
          meta: { title: '下单' },
          component: () => import('@/views/shipper/OrderCreate.vue'),
        },
        {
          path: 'orders/:id',
          name: 'shipper-order-detail',
          meta: { title: '订单详情' },
          component: () => import('@/views/shipper/OrderDetail.vue'),
        },
        {
          path: 'addresses',
          name: 'shipper-addresses',
          meta: { title: '常用地址和信息' },
          component: () => import('@/views/shipper/AddressManage.vue'),
        },
        {
          path: 'ledger',
          name: 'shipper-ledger',
          meta: { title: '我的账本' },
          component: () => import('@/views/shipper/ShipperLedger.vue'),
        },
      ],
    },
    {
      path: '/driver',
      component: () => import('@/layouts/MainLayout.vue'),
      meta: { role: 'driver' },
      children: [
        {
          path: '',
          redirect: 'open',
        },
        {
          path: 'open',
          name: 'driver-open',
          meta: { title: '未完成订单', hideBack: true, driverTab: true },
          component: () => import('@/views/driver/DriverOpenOrders.vue'),
        },
        {
          path: 'completed',
          name: 'driver-completed',
          meta: { title: '已完成订单', hideBack: true, driverTab: true },
          component: () => import('@/views/driver/DriverCompletedOrders.vue'),
        },
        {
          path: 'orders/:id',
          name: 'driver-order-detail',
          meta: { title: '订单详情' },
          component: () => import('@/views/shipper/OrderDetail.vue'),
        },
      ],
    },
    {
      path: '/dispatcher',
      component: () => import('@/layouts/MainLayout.vue'),
      meta: { role: 'dispatcher' },
      children: [
        {
          path: '',
          redirect: 'pending',
        },
        {
          path: 'pending',
          name: 'dispatcher-pending',
          meta: { title: '派单工作台', hideBack: true, dispatcherTab: true },
          component: () => import('@/views/dispatcher/DispatcherPending.vue'),
        },
        {
          path: 'completed',
          name: 'dispatcher-completed',
          meta: { title: '已送达订单', hideBack: true, dispatcherTab: true },
          component: () => import('@/views/dispatcher/DispatcherCompleted.vue'),
        },
        {
          path: 'orders/create',
          name: 'dispatcher-order-create',
          meta: { title: '代下单' },
          component: () => import('@/views/shipper/OrderCreate.vue'),
        },
        {
          path: 'orders/:id',
          name: 'dispatcher-order-detail',
          meta: { title: '订单详情' },
          component: () => import('@/views/shipper/OrderDetail.vue'),
        },
        {
          path: 'dashboard',
          name: 'dispatcher-dashboard',
          meta: { title: '数据看板', hideBack: true, dispatcherTab: true },
          component: () => import('@/views/dispatcher/DispatcherDashboard.vue'),
        },
        {
          path: 'prices',
          name: 'dispatcher-prices',
          meta: { title: '价格管理', hideBack: true, dispatcherTab: true },
          component: () => import('@/views/dispatcher/DispatcherPrices.vue'),
        },
        {
          path: 'ledger',
          name: 'dispatcher-ledger',
          meta: { title: '货主账本', hideBack: true, dispatcherTab: true },
          component: () => import('@/views/dispatcher/DispatcherLedger.vue'),
        },
      ],
    },
    {
      path: '/:pathMatch(.*)*',
      name: 'not-found',
      meta: { public: true },
      component: () => import('@/views/NotFound.vue'),
    },
  ],
})

function roleHome(role: string | null | undefined) {
  if (role === 'shipper') return '/shipper'
  if (role === 'driver') return '/driver/open'
  if (role === 'dispatcher') return '/dispatcher/pending'
  return '/login'
}

router.beforeEach(async (to) => {
  const auth = useAuthStore()

  if (auth.isAuthenticated && !auth.role) {
    await auth.ensureRoleHydrated()
  }

  if (to.meta.public) {
    if (to.name === 'login' && auth.isAuthenticated && auth.role) {
      return { path: roleHome(auth.role) }
    }
    return true
  }

  if (!auth.isAuthenticated) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }

  const need = to.matched.find((r) => r.meta.role)?.meta.role as string | undefined
  if (need && auth.role !== need) {
    return { path: roleHome(auth.role) }
  }

  return true
})

export default router
