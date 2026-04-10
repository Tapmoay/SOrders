<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showConfirmDialog, showFailToast, showLoadingToast, closeToast } from 'vant'

import { cancelOrder, deleteCancelledOrder, fetchOrders } from '@/api/orders'
import VirtualScrollList from '@/components/VirtualScrollList.vue'
import { ORDER_STATUS_LABEL, orderStatusTagType } from '@/constants/order'
import { shipperOrdersRefreshTick } from '@/shipperRealtimeState'
import type { Order, OrderProduct, OrderStatus } from '@/types/order'

const router = useRouter()
const route = useRoute()

/** 与路由 query 同步：delivered → 已送达；history → 全部（避免「历史」被误做成仅已送达导致其它状态订单「消失」） */
function tabIndexFromQuery(): number {
  const t = route.query.tab
  if (t === 'delivered') return 3
  if (t === 'history' || t === 'all') return 0
  if (t === 'cancelled') return 4
  if (t === 'accepted') return 2
  if (t === 'pending') return 1
  return 0
}

const tabIndex = ref(tabIndexFromQuery())
const tabs: { title: string; status?: OrderStatus }[] = [
  { title: '全部' },
  { title: '派单中', status: 'PENDING_DISPATCH' },
  { title: '已接单', status: 'ACCEPTED' },
  { title: '已送达', status: 'DELIVERED' },
  { title: '已撤销', status: 'CANCELLED' },
]

const list = ref<Order[]>([])
const loading = ref(false)
const refreshing = ref(false)

function ord(x: unknown): Order {
  return x as Order
}

async function load(silent = false) {
  if (!silent) loading.value = true
  if (!silent) {
    showLoadingToast({ message: '加载中…', forbidClick: true, duration: 0 })
  }
  try {
    const st = tabs[tabIndex.value].status
    list.value = await fetchOrders(st)
  } catch {
    showFailToast('加载失败')
  } finally {
    if (!silent) closeToast()
    if (!silent) loading.value = false
  }
}

async function onRefresh() {
  await load(true)
  refreshing.value = false
}

watch(tabIndex, () => load(), { immediate: true })

watch(
  () => route.query.tab,
  () => {
    const next = tabIndexFromQuery()
    if (tabIndex.value !== next) tabIndex.value = next
    else void load(true)
  },
)

watch(shipperOrdersRefreshTick, () => {
  void load(true)
})

function shortAddr(s: string) {
  if (!s) return '—'
  return s.length > 24 ? `${s.slice(0, 24)}…` : s
}

/** 按明细 id 去重，避免 ORM/接口偶发重复行导致「等2种」误判 */
function distinctOrderProducts(raw: OrderProduct[] | undefined): OrderProduct[] {
  const list = raw ?? []
  const seen = new Set<number>()
  const out: OrderProduct[] = []
  for (const p of list) {
    if (typeof p.id === 'number') {
      if (seen.has(p.id)) continue
      seen.add(p.id)
    }
    out.push(p)
  }
  return out
}

function productSummary(o: Order) {
  const lines = distinctOrderProducts(o.order_products)
  if (lines.length === 0) return '—'
  if (lines.length === 1) return `${lines[0].product_name_snapshot}×${lines[0].quantity}`
  return `${lines[0].product_name_snapshot} 等${lines.length}种`
}

function call(phone: string) {
  window.location.href = `tel:${phone}`
}

function goDetail(id: number) {
  router.push(`/shipper/orders/${id}`)
}

async function tryCancel(o: Order) {
  if (o.status !== 'PENDING_DISPATCH') return
  try {
    await showConfirmDialog({
      title: '撤销订单',
      message: `确定撤销订单 ${o.order_no}？`,
    })
    showLoadingToast({ message: '处理中…', forbidClick: true })
    await cancelOrder(o.id)
    closeToast()
    await load()
  } catch (e) {
    closeToast()
    if (e !== 'cancel') {
      const err = e as { response?: { data?: { detail?: string } } }
      showFailToast(err.response?.data?.detail || '撤销失败')
    }
  }
}

async function tryDeleteCancelled(o: Order) {
  if (o.status !== 'CANCELLED') return
  try {
    await showConfirmDialog({
      title: '删除订单',
      message: `删除后不可恢复，确定删除订单 ${o.order_no}？`,
    })
    showLoadingToast({ message: '处理中…', forbidClick: true })
    await deleteCancelledOrder(o.id)
    closeToast()
    await load()
  } catch (e) {
    closeToast()
    if (e !== 'cancel') {
      const err = e as { response?: { data?: { detail?: string } } }
      showFailToast(err.response?.data?.detail || '删除失败')
    }
  }
}
</script>

<template>
  <div class="order-list">
    <van-tabs v-model:active="tabIndex" shrink class="order-list__tabs">
      <van-tab v-for="(t, i) in tabs" :key="i" :title="t.title" />
    </van-tabs>

    <van-notice-bar
      v-if="tabIndex === 4"
      left-icon="info-o"
      wrapable
      :scrollable="false"
      text="已撤销订单仅保留 10 天，到期后由系统自动删除；如需留档请及时自行保存。"
    />

    <van-pull-refresh v-model="refreshing" @refresh="onRefresh">
      <van-empty v-if="!loading && list.length === 0" description="暂无订单" />

      <VirtualScrollList v-else :items="list" :estimate-size="200">
        <template #default="{ item }">
          <div v-for="o in [ord(item)]" :key="o.id" class="card" @click="goDetail(o.id)">
            <div class="card-top">
              <span class="no">{{ o.order_no }}</span>
              <van-tag :type="orderStatusTagType(o.status)" plain>{{ ORDER_STATUS_LABEL[o.status] }}</van-tag>
            </div>
            <div class="row muted">{{ o.order_date }} · {{ productSummary(o) }}</div>
            <div class="row">{{ shortAddr(o.address_detail) }}</div>
            <div v-if="o.status === 'ACCEPTED' && o.driver_phone" class="row driver" @click.stop>
              <span>司机 {{ o.driver_name || '—' }}</span>
              <van-button type="primary" size="mini" plain @click="call(o.driver_phone!)">拨打 {{ o.driver_phone }}</van-button>
            </div>
            <div v-if="o.status === 'PENDING_DISPATCH'" class="actions" @click.stop>
              <van-button size="small" type="danger" plain @click="tryCancel(o)">撤销订单</van-button>
              <van-button size="small" type="primary" plain @click="goDetail(o.id)">详情</van-button>
            </div>
            <div v-else-if="o.status === 'CANCELLED'" class="actions" @click.stop>
              <van-button size="small" type="danger" plain @click="tryDeleteCancelled(o)">删除</van-button>
              <van-button size="small" type="primary" plain @click="goDetail(o.id)">查看详情</van-button>
            </div>
            <div v-else class="actions" @click.stop>
              <van-button size="small" type="primary" plain @click="goDetail(o.id)">查看详情</van-button>
            </div>
          </div>
        </template>
      </VirtualScrollList>
    </van-pull-refresh>
  </div>
</template>

<style scoped>
.order-list {
  padding-bottom: 16px;
}

.order-list__tabs :deep(.van-tabs__wrap) {
  background: var(--van-background-2);
  border-bottom: 1px solid var(--van-border-color);
}

.order-list__tabs :deep(.van-tab) {
  font-weight: 500;
}

.card {
  margin: 10px 12px;
  padding: 14px 12px;
  background: var(--van-background-2);
  border: 1px solid var(--van-border-color);
  border-radius: var(--van-radius-lg, 12px);
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.05);
}
.card-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  gap: 8px;
}
.no {
  font-weight: 600;
  font-size: 16px;
  color: var(--van-text-color);
  letter-spacing: -0.01em;
}
.row {
  font-size: 14px;
  margin-top: 6px;
  line-height: 1.5;
}
.muted {
  color: var(--van-text-color-2);
}
.driver {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 8px;
}
.actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 10px;
}
</style>
