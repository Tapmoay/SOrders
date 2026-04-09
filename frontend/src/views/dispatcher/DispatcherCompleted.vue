<script setup lang="ts">
import { showFailToast } from 'vant'
import { onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { fetchOrders } from '@/api/orders'
import VirtualScrollList from '@/components/VirtualScrollList.vue'
import { formatApiError } from '@/utils/apiError'
import { ORDER_STATUS_LABEL, orderStatusTagType } from '@/constants/order'
import type { Order } from '@/types/order'

const router = useRouter()
const searchText = ref('')
const debouncedQ = ref('')
let searchTimer: ReturnType<typeof setTimeout> | null = null

watch(searchText, (v) => {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    debouncedQ.value = v.trim()
  }, 400)
})

const list = ref<Order[]>([])
const loading = ref(false)
const refreshing = ref(false)

function fmtTime(iso: string | null | undefined) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

function addrShort(s: string) {
  if (!s) return '—'
  return s.length > 36 ? `${s.slice(0, 36)}…` : s
}

function ord(x: unknown): Order {
  return x as Order
}

function productLine(o: Order) {
  if (!o.order_products?.length) return o.delivery_description || '—'
  return o.order_products.map((p) => `${p.product_name_snapshot}×${p.quantity}`).join('；')
}

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    list.value = await fetchOrders('DELIVERED', debouncedQ.value || undefined)
  } catch (e: unknown) {
    showFailToast(formatApiError(e, '加载失败'))
  } finally {
    if (!silent) loading.value = false
  }
}

async function onRefresh() {
  await load(true)
  refreshing.value = false
}

watch(debouncedQ, () => {
  void load(true)
})

onMounted(() => {
  void load()
})

function openDetail(o: Order) {
  void router.push({ name: 'dispatcher-order-detail', params: { id: String(o.id) } })
}
</script>

<template>
  <div class="dispatch-done role-tool-page">
    <div class="role-tool-notice">
      <van-notice-bar left-icon="info-o" text="仅展示已送达订单，支持关键字筛选。" />
    </div>
    <van-search v-model="searchText" placeholder="订单号 / 货主 / 地址 / 司机" />

    <van-pull-refresh v-model="refreshing" @refresh="onRefresh">
      <van-empty v-if="!loading && !list.length" description="暂无已送达订单" />

      <VirtualScrollList v-else :items="list" :estimate-size="200">
        <template #default="{ item }">
          <div v-for="o in [ord(item)]" :key="o.id" class="card" role="button" tabindex="0" @click="openDetail(o)">
            <div class="head">
              <span class="no">{{ o.order_no }}</span>
              <van-tag :type="orderStatusTagType(o.status)" plain>{{ ORDER_STATUS_LABEL[o.status] }}</van-tag>
            </div>
            <div class="row"><span class="k">货主</span>{{ o.shipper_name || '—' }}</div>
            <div class="row"><span class="k">司机</span>{{ o.driver_name || '—' }}</div>
            <div class="row full"><span class="k">商品</span>{{ productLine(o) }}</div>
            <div class="row full"><span class="k">地址</span>{{ addrShort(o.address_detail) }}</div>
            <div class="row"><span class="k">下单</span>{{ fmtTime(o.created_at) }}</div>
            <div class="row"><span class="k">送达</span>{{ fmtTime(o.delivered_at) }}</div>
          </div>
        </template>
      </VirtualScrollList>
    </van-pull-refresh>
  </div>
</template>

<style scoped>
.dispatch-done {
  padding-bottom: 8px;
}
.card {
  margin: 8px 12px;
  padding: 11px 12px;
  background: var(--van-background-2, #fff);
  border: 1px solid var(--van-border-color);
  border-radius: var(--van-radius-lg, 12px);
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.05);
  font-size: 14px;
  cursor: pointer;
}
.card:active {
  opacity: 0.92;
}
.head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}
.no {
  font-weight: 600;
  font-size: 16px;
  color: var(--van-text-color);
}
.row {
  display: flex;
  gap: 8px;
  margin-bottom: 4px;
}
.row:last-child {
  margin-bottom: 0;
}
.row.full {
  flex-wrap: wrap;
}
.k {
  color: var(--van-text-color-2, #646566);
  flex-shrink: 0;
  width: 3em;
}
</style>
