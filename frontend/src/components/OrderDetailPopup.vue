<script setup lang="ts">
import { showFailToast, showLoadingToast, closeToast } from 'vant'
import { ref, watch } from 'vue'

import { fetchOrder } from '@/api/orders'
import OrderDetailBody from '@/components/OrderDetailBody.vue'
import type { Order } from '@/types/order'

const props = defineProps<{
  show: boolean
  orderId: number | null
  viewerRole: 'shipper' | 'dispatcher' | 'driver'
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
}>()

const order = ref<Order | null>(null)
const loading = ref(false)

async function load() {
  if (!props.orderId) {
    order.value = null
    return
  }
  loading.value = true
  showLoadingToast({ message: '加载中…', forbidClick: true, duration: 0 })
  try {
    order.value = await fetchOrder(props.orderId)
  } catch {
    showFailToast('加载失败')
    order.value = null
    emit('update:show', false)
  } finally {
    loading.value = false
    closeToast()
  }
}

watch(
  () => [props.show, props.orderId] as const,
  ([open, id]) => {
    if (open && id) void load()
    if (!open) order.value = null
  },
)

async function onReload() {
  await load()
}
</script>

<template>
  <van-popup
    :show="show"
    position="center"
    round
    teleport="body"
    :style="{ width: 'min(92vw, 440px)', maxHeight: '88vh' }"
    class="order-detail-popup"
    @update:show="emit('update:show', $event)"
  >
    <div class="odp">
      <div class="odp__bar">
        <span class="odp__title">订单详情</span>
        <van-icon name="cross" class="odp__close" @click="emit('update:show', false)" />
      </div>
      <div class="odp__scroll">
        <van-loading v-if="loading" vertical class="odp__loading">加载中…</van-loading>
        <OrderDetailBody
          v-else-if="order"
          :order="order"
          :viewer-role="viewerRole"
          @reload="onReload"
        />
        <van-empty v-else description="暂无数据" />
      </div>
    </div>
  </van-popup>
</template>

<style scoped>
.odp {
  display: flex;
  flex-direction: column;
  max-height: 88vh;
  background: var(--van-background-2, #fff);
}

.odp__bar {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px 10px;
  border-bottom: 1px solid var(--van-border-color);
}

.odp__title {
  font-size: 16px;
  font-weight: 600;
  color: var(--van-text-color);
}

.odp__close {
  font-size: 20px;
  color: var(--van-text-color-2);
  padding: 4px;
  cursor: pointer;
}

.odp__scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
  padding: 12px 12px max(16px, env(safe-area-inset-bottom));
}

.odp__loading {
  padding: 48px 0;
}
</style>
