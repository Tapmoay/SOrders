<script setup lang="ts">
import { showFailToast, showLoadingToast, showSuccessToast, closeToast } from 'vant'
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'

import {
  appendDriverNote,
  completeOrderWithUpload,
  driverAckOrder,
  fetchOrders,
} from '@/api/orders'
import { driverOrdersRefreshTick } from '@/driverRealtimeState'
import type { Order } from '@/types/order'
import { openAmapNavigation } from '@/utils/amapNav'
import VirtualScrollList from '@/components/VirtualScrollList.vue'
import {
  bumpRetry,
  listOfflineQueue,
  queueOfflineDelivery,
  removeOfflineQueueItem,
  setQueueItemError,
  type OfflineDeliveryQueueItem,
} from '@/utils/offlineDeliveryQueue'
import { addWatermarkToBlob, buildDeliveryWatermarkLines } from '@/utils/watermark'

const loading = ref(false)
const refreshing = ref(false)
const orders = ref<Order[]>([])
const queueCount = ref(0)
const queueItems = ref<OfflineDeliveryQueueItem[]>([])
const uploadProgress = ref(0)
const syncing = ref(false)
const syncLabel = ref('')

const noteDraft = reactive<Record<number, string>>({})
const fileInputRefs = new Map<number, HTMLInputElement>()

const drafts = reactive<
  Record<number, { files: File[]; previews: string[]; remark: string }>
>({})

function ord(x: unknown): Order {
  return x as Order
}

function addrShort(o: Order) {
  const t = o.address_detail?.trim() || ''
  return t.length > 36 ? `${t.slice(0, 36)}…` : t
}

function productLine(o: Order) {
  if (!o.order_products?.length) return o.delivery_description || '—'
  return o.order_products.map((p) => `${p.product_name_snapshot}×${p.quantity}`).join('；')
}

function ensureDraft(orderId: number) {
  if (!drafts[orderId]) {
    drafts[orderId] = { files: [], previews: [], remark: '' }
  }
  return drafts[orderId]!
}

async function loadOrders(forPull = false) {
  if (!forPull) loading.value = true
  try {
    orders.value = await fetchOrders('ACCEPTED')
  } catch (e: unknown) {
    showFailToast((e as Error)?.message || '加载失败')
  } finally {
    if (!forPull) loading.value = false
  }
}

async function onRefresh() {
  await loadOrders(true)
  refreshing.value = false
}

function setFileRef(orderId: number, el: unknown) {
  if (el instanceof HTMLInputElement) fileInputRefs.set(orderId, el)
  else fileInputRefs.delete(orderId)
}

async function refreshQueueCount() {
  const q = await listOfflineQueue()
  queueItems.value = q
  queueCount.value = q.length
}

async function syncOfflineQueue() {
  if (!navigator.onLine || syncing.value) return
  const items = await listOfflineQueue()
  if (!items.length) return
  syncing.value = true
  uploadProgress.value = 0
  syncLabel.value = ''
  try {
    for (let idx = 0; idx < items.length; idx++) {
      const it = items[idx]!
      const label = it.orderNo ? `#${it.orderNo}` : `#${it.orderId}`
      syncLabel.value = `同步 ${label} (${idx + 1}/${items.length})`
      const files = it.blobs.map(
        (b, i) => new File([b], `delivery-${i}.jpg`, { type: 'image/jpeg' }),
      )
      try {
        const note = (it.internalNoteAppend || '').trim()
        if (note) {
          await appendDriverNote(it.orderId, note)
        }
        await completeOrderWithUpload(it.orderId, files, it.driverRemark, (p) => {
          uploadProgress.value = p
        })
        await removeOfflineQueueItem(it.id)
        showSuccessToast(`${label} 已同步`)
      } catch (e) {
        const msg = (e as Error)?.message || '上传失败'
        await setQueueItemError(it.id, msg)
        await bumpRetry(it.id)
        showFailToast(`${label} 同步失败，将重试`)
      }
    }
    await loadOrders(true)
  } finally {
    syncing.value = false
    uploadProgress.value = 0
    syncLabel.value = ''
    await refreshQueueCount()
  }
}

async function manualSyncQueue() {
  await syncOfflineQueue()
}

function onOnline() {
  void syncOfflineQueue()
}

watch(driverOrdersRefreshTick, () => {
  void loadOrders(true)
})

watch(
  orders,
  (list) => {
    for (const o of list) {
      ensureDraft(o.id)
      if (noteDraft[o.id] === undefined) noteDraft[o.id] = ''
    }
  },
  { immediate: true },
)

async function onAckNew(o: Order) {
  if (!o.is_new_for_driver) return
  try {
    const updated = await driverAckOrder(o.id)
    const idx = orders.value.findIndex((x) => x.id === o.id)
    if (idx >= 0) orders.value[idx] = updated
  } catch {
    /* ignore */
  }
}

function triggerPick(orderId: number) {
  const o = orders.value.find((x) => x.id === orderId)
  if (o) void onAckNew(o)
  fileInputRefs.get(orderId)?.click()
}

async function onFiles(orderId: number, e: Event) {
  const input = e.target as HTMLInputElement
  const list = input.files
  if (!list?.length) return
  const order = orders.value.find((x) => x.id === orderId)
  if (!order) return

  showLoadingToast({ message: '处理照片…', forbidClick: true, duration: 0 })
  try {
    const locLine = await locationLine(order.address_detail || '')
    const lines = buildDeliveryWatermarkLines(locLine)
    const d = ensureDraft(orderId)
    for (const old of d.previews) {
      URL.revokeObjectURL(old)
    }
    d.files = []
    d.previews = []
    for (let i = 0; i < list.length; i++) {
      const raw = list[i]!
      const wm = await addWatermarkToBlob(raw, lines)
      const file = new File([wm], `wm-${i}.jpg`, { type: 'image/jpeg' })
      d.files.push(file)
      d.previews.push(URL.createObjectURL(file))
    }
  } catch (err) {
    showFailToast((err as Error)?.message || '处理失败')
  } finally {
    closeToast()
    input.value = ''
  }
}

function locationLine(fallbackAddress: string): Promise<string> {
  return new Promise((resolve) => {
    if (!navigator.geolocation) {
      resolve(fallbackAddress ? fallbackAddress.slice(0, 48) : '')
      return
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        resolve(
          `GPS ${pos.coords.latitude.toFixed(5)}, ${pos.coords.longitude.toFixed(5)}`,
        )
      },
      () => resolve(fallbackAddress ? fallbackAddress.slice(0, 48) : ''),
      { timeout: 6000, maximumAge: 120_000 },
    )
  })
}

function removePhoto(orderId: number, index: number) {
  const d = drafts[orderId]
  if (!d) return
  const u = d.previews[index]
  if (u) URL.revokeObjectURL(u)
  d.previews.splice(index, 1)
  d.files.splice(index, 1)
}

function onNavigate(o: Order) {
  void onAckNew(o)
  const lat = o.address_lat != null ? Number(o.address_lat) : NaN
  const lng = o.address_lng != null ? Number(o.address_lng) : NaN
  if (Number.isFinite(lat) && Number.isFinite(lng)) {
    openAmapNavigation(lng, lat, o.address_detail || o.order_no)
  } else {
    const q = encodeURIComponent(o.address_detail || o.order_no)
    window.open(`https://uri.amap.com/search?query=${q}`, '_blank', 'noopener,noreferrer')
  }
}

async function complete(orderId: number) {
  const d = ensureDraft(orderId)
  if (!d.files.length) {
    showFailToast('请至少上传一张照片')
    return
  }
  const remark = d.remark || ''
  const pendingInternal = (noteDraft[orderId] || '').trim()
  const current = orders.value.find((x) => x.id === orderId)

  if (!navigator.onLine) {
    const id = crypto.randomUUID()
    const blobs = await Promise.all(
      d.files.map(async (f) => {
        const ab = await f.arrayBuffer()
        return new Blob([ab], { type: 'image/jpeg' })
      }),
    )
    const item: OfflineDeliveryQueueItem = {
      id,
      orderId,
      orderNo: current?.order_no ?? '',
      driverRemark: remark,
      internalNoteAppend: pendingInternal || undefined,
      blobs,
      createdAt: Date.now(),
      retries: 0,
    }
    await queueOfflineDelivery(item)
    for (const u of d.previews) URL.revokeObjectURL(u)
    d.files = []
    d.previews = []
    d.remark = ''
    noteDraft[orderId] = ''
    await refreshQueueCount()
    showSuccessToast('已离线保存，联网后将自动上传')
    return
  }

  showLoadingToast({ message: '上传中…', forbidClick: true, duration: 0 })
  try {
    if (pendingInternal) {
      const updated = await appendDriverNote(orderId, pendingInternal)
      const idx = orders.value.findIndex((x) => x.id === orderId)
      if (idx >= 0) orders.value[idx] = updated
      noteDraft[orderId] = ''
    }
    await completeOrderWithUpload(orderId, d.files, remark, (p) => {
      uploadProgress.value = p
    })
    for (const u of d.previews) URL.revokeObjectURL(u)
    d.files = []
    d.previews = []
    d.remark = ''
    uploadProgress.value = 0
    closeToast()
    showSuccessToast('订单已完成')
    await loadOrders()
  } catch (e: unknown) {
    closeToast()
    showFailToast((e as Error)?.message || '提交失败')
  }
}

const canNotify = computed(
  () => typeof Notification !== 'undefined' && Notification.permission === 'default',
)

function requestNotify() {
  if (!('Notification' in window)) return
  void Notification.requestPermission()
}

onMounted(() => {
  void loadOrders()
  void refreshQueueCount()
  void syncOfflineQueue()
  window.addEventListener('online', onOnline)
  if ('Notification' in window && Notification.permission === 'default') {
    void Notification.requestPermission()
  }
})

onUnmounted(() => {
  window.removeEventListener('online', onOnline)
  for (const d of Object.values(drafts)) {
    for (const u of d.previews) URL.revokeObjectURL(u)
  }
})
</script>

<template>
  <div class="driver-open role-tool-page">
    <div v-if="queueCount > 0 || syncing" class="role-tool-notice">
      <van-notice-bar
        v-if="queueCount > 0"
        left-icon="warning-o"
        :text="`离线队列 ${queueCount} 单待同步`"
      />
      <van-notice-bar
        v-if="syncing"
        left-icon="upgrade"
        :text="`${syncLabel || '同步中'} ${uploadProgress ? uploadProgress + '%' : ''}`"
      />
    </div>
    <div v-if="canNotify" class="notify-hint">
      <van-button size="small" type="primary" plain @click="requestNotify">开启系统通知</van-button>
    </div>

    <van-cell-group v-if="queueItems.length" inset class="q-panel">
      <van-cell title="离线送达队列" :label="`${queueItems.length} 单待上传`">
        <template #value>
          <van-button size="small" type="primary" :loading="syncing" @click="manualSyncQueue">
            立即同步
          </van-button>
        </template>
      </van-cell>
      <van-cell
        v-for="q in queueItems"
        :key="q.id"
        :title="q.orderNo || `订单 #${q.orderId}`"
        :label="q.lastError ? `上次错误: ${q.lastError}` : `重试 ${q.retries} 次`"
      />
    </van-cell-group>

    <van-pull-refresh v-model="refreshing" @refresh="onRefresh">
      <van-empty v-if="!loading && !orders.length" description="暂无未完成订单" />
      <VirtualScrollList v-else :items="orders" :estimate-size="420">
        <template #default="{ item }">
          <div v-for="o in [ord(item)]" :key="o.id" class="card">
        <div class="card-head">
          <RouterLink
            class="order-no"
            :to="{ name: 'driver-order-detail', params: { id: String(o.id) } }"
            @click.stop
          >
            {{ o.order_no }}
          </RouterLink>
          <van-icon v-if="o.is_new_for_driver" name="warning-o" class="new-ico" />
        </div>
        <div class="row">
          <span class="label">货主</span>
          <span>{{ o.shipper_name || '—' }}</span>
        </div>
        <div class="row">
          <span class="label">地址</span>
          <span>{{ addrShort(o) }}</span>
        </div>
        <div class="row">
          <span class="label">商品</span>
          <span class="wrap">{{ productLine(o) }}</span>
        </div>
        <div class="remark-photos-block">
          <div class="hp-row">
            <div class="hp-label">内部备注</div>
            <div class="hp-main">
              <div class="internal-body">{{ o.internal_notes || '（无）' }}</div>
              <van-field
                v-model="noteDraft[o.id]"
                rows="2"
                autosize
                type="textarea"
                placeholder="追加备注（点「完成订单」时自动保存）"
                maxlength="2000"
                class="note-field"
              />
            </div>
          </div>
          <div class="hp-row hp-row--photos">
            <div class="hp-label">
              送达照片<span class="hp-req">（必填）</span>
            </div>
            <div class="hp-main hp-main--photos">
              <div class="thumbs">
                <div v-for="(src, i) in ensureDraft(o.id).previews" :key="i" class="thumb-wrap">
                  <img :src="src" alt="" class="thumb" />
                  <van-icon name="cross" class="rm" @click="removePhoto(o.id, i)" />
                </div>
              </div>
              <input
                :ref="(el) => setFileRef(o.id, el)"
                type="file"
                accept="image/*"
                multiple
                capture="environment"
                class="hidden-input"
                @change="onFiles(o.id, $event)"
              />
              <van-button size="small" icon="photograph" @click="triggerPick(o.id)">
                拍照 / 相册（可多选）
              </van-button>
            </div>
          </div>
        </div>

        <van-field
          v-model="ensureDraft(o.id).remark"
          label="完成备注"
          placeholder="选填"
          maxlength="2000"
        />

        <div class="actions">
          <van-button size="small" type="primary" plain icon="guide-o" @click="onNavigate(o)">
            导航
          </van-button>
          <van-button
            size="small"
            type="success"
            :disabled="!ensureDraft(o.id).files.length"
            @click="complete(o.id)"
          >
            完成订单
          </van-button>
        </div>
          </div>
        </template>
      </VirtualScrollList>
    </van-pull-refresh>
  </div>
</template>

<style scoped>
.driver-open {
  padding: 8px 12px 24px;
}
.notify-hint {
  margin-bottom: 8px;
}
.q-panel {
  margin: 8px 12px;
}
.card {
  background: var(--van-background-2, #fff);
  border: 1px solid var(--van-border-color);
  border-radius: var(--van-radius-lg, 12px);
  padding: 11px 12px;
  margin-bottom: 12px;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.05);
}
.card-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
  font-weight: 600;
}
.order-no {
  font-size: 16px;
  color: var(--van-primary-color, #1677ff);
  text-decoration: underline;
  font-weight: 600;
}
.new-ico {
  color: var(--van-danger-color, #ee0a24);
  font-size: 20px;
}
.row {
  display: flex;
  gap: 8px;
  margin-bottom: 4px;
  font-size: 14px;
}
.label {
  color: var(--van-text-color-2, #646566);
  flex-shrink: 0;
  width: 40px;
}
.wrap {
  word-break: break-all;
}
.remark-photos-block {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--van-border-color, #ebedf0);
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.hp-row {
  display: flex;
  flex-direction: row;
  align-items: flex-start;
  gap: 10px;
}
.hp-row--photos {
  align-items: flex-start;
}
.hp-label {
  flex-shrink: 0;
  width: 72px;
  font-size: 13px;
  color: var(--van-text-color-2, #646566);
  line-height: 1.35;
}
.hp-req {
  display: inline;
  font-size: 12px;
  color: var(--van-danger-color, #ee0a24);
}
.hp-main {
  flex: 1;
  min-width: 0;
}
.hp-main--photos {
  display: flex;
  flex-direction: row;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.internal-body {
  white-space: pre-wrap;
  font-size: 13px;
  color: var(--van-text-color-2, #646566);
  margin-bottom: 6px;
}
.note-field {
  padding-left: 0 !important;
  padding-right: 0 !important;
}
.thumbs {
  display: flex;
  flex-direction: row;
  flex-wrap: wrap;
  gap: 8px;
}
.thumb-wrap {
  position: relative;
  width: 72px;
  height: 72px;
}
.thumb {
  width: 72px;
  height: 72px;
  object-fit: cover;
  border-radius: 6px;
}
.rm {
  position: absolute;
  top: -6px;
  right: -6px;
  background: rgba(0, 0, 0, 0.55);
  color: #fff;
  border-radius: 50%;
  padding: 4px;
  font-size: 12px;
}
.hidden-input {
  display: none;
}
.actions {
  display: flex;
  gap: 8px;
  margin-top: 10px;
  justify-content: flex-end;
}
</style>
