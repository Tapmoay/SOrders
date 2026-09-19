<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showConfirmDialog, showFailToast, showLoadingToast, closeToast } from 'vant'

import { cancelOrder, deleteCancelledOrder, fetchOrdersPage } from '@/api/orders'
import VirtualScrollList from '@/components/VirtualScrollList.vue'
import { CANCELLABLE_STATUSES, ORDER_STATUS_LABEL, orderStatusTagType } from '@/constants/order'
import { shipperOrdersRefreshTick } from '@/shipperRealtimeState'
import type { Order, OrderProduct, OrderStatus } from '@/types/order'

const router = useRouter()
const route = useRoute()

/**
 * 五个状态**每一档都要有页面能看到**（2026-09-19 审计 H1）。
 * 原来只有「派单中/已接单/已送达/已撤销」四个页签，缺 `DISPATCHED`——
 * 货主刚下的单被派出去、司机还没接的那段时间，这张单在 H5 上**任何列表里都不存在**，
 * 用户视角就是"我的订单不见了"。
 */
const tabs: { title: string; status?: OrderStatus }[] = [
  { title: '全部' },
  { title: '派单中', status: 'PENDING_DISPATCH' },
  { title: '已派单', status: 'DISPATCHED' },
  { title: '已接单', status: 'ACCEPTED' },
  { title: '已送达', status: 'DELIVERED' },
  { title: '已撤销', status: 'CANCELLED' },
]

/** 深链 `?tab=` → 页签下标。**按状态查表，不写死数字**（写死时插一个页签就全错位）。 */
const TAB_QUERY_STATUS: Record<string, OrderStatus> = {
  pending: 'PENDING_DISPATCH',
  dispatched: 'DISPATCHED',
  accepted: 'ACCEPTED',
  delivered: 'DELIVERED',
  cancelled: 'CANCELLED',
}

/** 与路由 query 同步：delivered → 已送达；history/all/未知 → 全部（避免「历史」被误做成仅已送达导致其它状态订单「消失」） */
function tabIndexFromQuery(): number {
  const t = route.query.tab
  const want = typeof t === 'string' ? TAB_QUERY_STATUS[t] : undefined
  if (!want) return 0
  const i = tabs.findIndex((x) => x.status === want)
  return i >= 0 ? i : 0
}

const tabIndex = ref(tabIndexFromQuery())

const list = ref<Order[]>([])
const loading = ref(false)
/** 服务端把这一页截断了（`X-Truncated`）：界面必须说出来，否则用户会以为「这就是全部」，据此判断某一单不存在 */
const truncated = ref(false)
/** 服务端本次的上限（`X-Result-Limit`）；读不到时为空 */
const resultLimit = ref<number | null>(null)
const truncatedText = computed(() => {
  const n = resultLimit.value
  const shown = n ? `最近 ${n} 条` : '一部分'
  return `只显示了${shown}，可能还有更早的没有列出来 —— 请用搜索或时间范围缩小范围。`
})
const refreshing = ref(false)

/** 当前页签对应的状态（「全部」为 undefined）。用 `?.` 兜住越界——本项目栽过一次下标越界崩页。 */
const currentStatus = computed<OrderStatus | undefined>(() => tabs[tabIndex.value]?.status)

function ord(x: unknown): Order {
  return x as Order
}

async function load(silent = false) {
  if (!silent) loading.value = true
  if (!silent) {
    showLoadingToast({ message: '加载中…', forbidClick: true, duration: 0 })
  }
  try {
    const page = await fetchOrdersPage(currentStatus.value)
    list.value = page.items
    truncated.value = page.truncated
    resultLimit.value = page.limit
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
  // 状态门只有一处真源（后端 `cancel_pending`）：待派单 + 已派单（司机还没接）。
  if (!CANCELLABLE_STATUSES.includes(o.status)) return
  const note =
    o.status === 'DISPATCHED'
      ? '该单已经派给司机（还没接单），撤销后司机会收到通知。'
      : '撤销后不可恢复。'
  try {
    await showConfirmDialog({
      title: '撤销订单',
      message: `确定撤销订单 ${o.order_no}？${note}`,
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
      v-if="currentStatus === 'CANCELLED'"
      left-icon="info-o"
      wrapable
      :scrollable="false"
      text="已撤销订单进入隔离区保留 30 天，到期后由系统自动删除；如需留档请及时自行保存。"
    />

    <van-notice-bar
      v-if="truncated"
      left-icon="info-o"
      wrapable
      :scrollable="false"
      :text="truncatedText"
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
            <div
              v-if="(o.status === 'DISPATCHED' || o.status === 'ACCEPTED') && o.driver_phone"
              class="row driver"
              @click.stop
            >
              <span>司机 {{ o.driver_name || '—' }}</span>
              <van-button type="primary" size="mini" plain @click="call(o.driver_phone!)">拨打 {{ o.driver_phone }}</van-button>
            </div>
            <div v-if="CANCELLABLE_STATUSES.includes(o.status)" class="actions" @click.stop>
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
