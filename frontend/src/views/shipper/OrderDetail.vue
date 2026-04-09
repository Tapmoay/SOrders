<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showFailToast, showLoadingToast, closeToast } from 'vant'

import { fetchOrder } from '@/api/orders'
import OrderDetailBody from '@/components/OrderDetailBody.vue'
import { driverOrdersRefreshTick } from '@/driverRealtimeState'
import { shipperOrdersRefreshTick } from '@/shipperRealtimeState'
import type { Order } from '@/types/order'

const route = useRoute()
const router = useRouter()
const id = computed(() => Number(route.params.id))
const isShipper = computed(() => route.path.startsWith('/shipper'))
const isDriver = computed(() => route.path.startsWith('/driver'))

const viewerRole = computed<'shipper' | 'dispatcher' | 'driver'>(() => {
  if (isShipper.value) return 'shipper'
  if (isDriver.value) return 'driver'
  return 'dispatcher'
})

const order = ref<Order | null>(null)

async function load() {
  showLoadingToast({ message: '加载中…', forbidClick: true, duration: 0 })
  try {
    order.value = await fetchOrder(id.value)
  } catch {
    showFailToast('加载失败')
    router.back()
  } finally {
    closeToast()
  }
}

onMounted(load)
watch(shipperOrdersRefreshTick, () => {
  if (isShipper.value) void load()
})
watch(driverOrdersRefreshTick, () => {
  if (isDriver.value) void load()
})
</script>

<template>
  <div v-if="order" class="detail" :class="{ 'detail--driver': isDriver }">
    <OrderDetailBody :order="order" :viewer-role="viewerRole" @reload="load" />
  </div>
</template>

<style scoped>
.detail {
  padding: 12px 0 max(24px, env(safe-area-inset-bottom));
}

.detail--driver {
  min-height: 100%;
  padding-top: 8px;
  background: var(--van-background, #f7f8fa);
}
</style>
