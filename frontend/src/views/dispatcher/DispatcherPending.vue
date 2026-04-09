<script setup lang="ts">
import {
  showConfirmDialog,
  showFailToast,
  showLoadingToast,
  showSuccessToast,
  closeToast,
} from 'vant'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { clearOrderDraft, orderDraftIsResumable } from '@/constants/orderDraft'

import {
  assignOrder,
  batchAssignOrders,
  cancelOrder,
  fetchOrders,
  recallOrder,
  updateOrder,
  updateOrderProduct,
  type OrderUpdateBody,
} from '@/api/orders'

/** 表单绑定用纯 string，避免 van-field 与 `| null` 不兼容 */
interface EditFormState {
  delivery_description: string
  address_detail: string
  address_lat: number | null
  address_lng: number | null
  contact_dongjia_phone: string
  contact_boss_phone: string
  remark: string
  internal_notes: string
}

/** 与后端订单明细行对应，字段用 string 便于 van-field 绑定 */
interface EditLineFormState {
  id: number
  product_name_snapshot: string
  quantity: string
  unit_price: string
}
import { fetchUsers, type UserListItem } from '@/api/user'
import AmapPicker from '@/components/AmapPicker.vue'
import VirtualScrollList from '@/components/VirtualScrollList.vue'
import { ORDER_STATUS_LABEL, orderStatusTagType } from '@/constants/order'
import type { Order, OrderStatus } from '@/types/order'
import { formatApiError } from '@/utils/apiError'

const router = useRouter()
/** 避免 Tab 切换卸载后仍弹出 Toast（请求晚返回） */
let viewAlive = true
onBeforeUnmount(() => {
  viewAlive = false
})
const hasOrderDraft = ref(false)

const tabIndex = ref(0)
const tabStatus = computed<OrderStatus>(() => (tabIndex.value === 0 ? 'PENDING_DISPATCH' : 'ACCEPTED'))

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
const drivers = ref<UserListItem[]>([])

const batchMode = ref(false)
const selectedIds = ref<number[]>([])

const showDispatch = ref(false)
const pickDriverVisible = ref(false)
const dispatchBatch = ref(false)
const dispatchDriverId = ref<number | null>(null)
const dispatchNote = ref('')

const showEdit = ref(false)
const showMapEdit = ref(false)
const editForm = ref<EditFormState>({
  delivery_description: '',
  address_detail: '',
  address_lat: null,
  address_lng: null,
  contact_dongjia_phone: '',
  contact_boss_phone: '',
  remark: '',
  internal_notes: '',
})
const editingId = ref<number | null>(null)
const editLines = ref<EditLineFormState[]>([])

const initialEditLngLat = computed(() => {
  const lng = editForm.value.address_lng
  const lat = editForm.value.address_lat
  if (lng == null || lat == null) return null
  const ln = Number(lng)
  const la = Number(lat)
  return Number.isFinite(ln) && Number.isFinite(la) ? { lng: ln, lat: la } : null
})

const showRecall = ref(false)
const recallReason = ref('')
const recallOrderId = ref<number | null>(null)

const selectedDriverLabel = computed(() => {
  if (!dispatchDriverId.value) return ''
  const d = drivers.value.find((x) => x.id === dispatchDriverId.value)
  return d ? `${d.full_name || '司机'} · ${d.phone}` : ''
})

function fmtTime(iso: string | undefined) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

function ord(x: unknown): Order {
  return x as Order
}

function addrShort(s: string) {
  if (!s) return '—'
  return s.length > 32 ? `${s.slice(0, 32)}…` : s
}

function productLine(o: Order) {
  if (!o.order_products?.length) return o.delivery_description || '—'
  return o.order_products.map((p) => `${p.product_name_snapshot}×${p.quantity}`).join('；')
}

async function loadDrivers() {
  try {
    drivers.value = await fetchUsers({ role: 'driver' })
  } catch (e: unknown) {
    if (!viewAlive) return
    showFailToast(formatApiError(e, '加载司机列表失败'))
  }
}

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    list.value = await fetchOrders(tabStatus.value, debouncedQ.value || undefined)
  } catch (e: unknown) {
    if (!viewAlive) return
    showFailToast(formatApiError(e, '加载失败'))
  } finally {
    if (!silent) loading.value = false
  }
}

async function onRefresh() {
  await load(true)
  refreshing.value = false
}

watch([tabIndex, debouncedQ], () => {
  void load(true)
})

watch(tabIndex, () => {
  batchMode.value = false
  selectedIds.value = []
})

function refreshDraftFlag() {
  hasOrderDraft.value = orderDraftIsResumable('dispatcher')
}

function goNewDispatcherOrder() {
  clearOrderDraft('dispatcher')
  refreshDraftFlag()
  void router.push({ name: 'dispatcher-order-create' })
}

function goResumeDispatcherDraft() {
  void router.push({ name: 'dispatcher-order-create', query: { resume: '1' } })
}

onMounted(() => {
  refreshDraftFlag()
  void loadDrivers()
  void load()
})

function toggleSelect(id: number, checked: boolean) {
  if (checked) {
    if (!selectedIds.value.includes(id)) selectedIds.value = [...selectedIds.value, id]
  } else {
    selectedIds.value = selectedIds.value.filter((x) => x !== id)
  }
}

function pickDriver(id: number) {
  dispatchDriverId.value = id
  pickDriverVisible.value = false
}

function openDispatchSingle(o: Order) {
  if (o.status !== 'PENDING_DISPATCH') return
  dispatchBatch.value = false
  editingId.value = o.id
  dispatchDriverId.value = null
  dispatchNote.value = ''
  showDispatch.value = true
}

function openBatchDispatch() {
  if (!selectedIds.value.length) {
    showFailToast('请先勾选订单')
    return
  }
  dispatchBatch.value = true
  dispatchDriverId.value = null
  dispatchNote.value = ''
  showDispatch.value = true
}

async function submitDispatch() {
  if (!dispatchDriverId.value) {
    showFailToast('请选择司机')
    return
  }
  showLoadingToast({ message: '提交中…', forbidClick: true, duration: 0 })
  try {
    if (dispatchBatch.value) {
      const res = await batchAssignOrders(
        selectedIds.value,
        dispatchDriverId.value,
        dispatchNote.value || undefined,
      )
      const ok = res.results.filter((r) => r.success).length
      const fail = res.results.length - ok
      showSuccessToast(`成功 ${ok} 单${fail ? `，失败 ${fail}` : ''}`)
      selectedIds.value = []
      batchMode.value = false
    } else if (editingId.value != null) {
      await assignOrder(editingId.value, dispatchDriverId.value, dispatchNote.value || undefined)
      showSuccessToast('派单成功')
    }
    showDispatch.value = false
    await load(true)
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } }
    showFailToast(err.response?.data?.detail || '派单失败')
  } finally {
    closeToast()
  }
}

function onEditMapConfirm(payload: { address: string; lng: number; lat: number }) {
  editForm.value.address_detail = payload.address
  editForm.value.address_lng = payload.lng
  editForm.value.address_lat = payload.lat
}

function fmtLineSub(line: EditLineFormState) {
  const q = parseInt(line.quantity, 10)
  const p = Number(String(line.unit_price).trim())
  if (!Number.isFinite(q) || !Number.isFinite(p)) return '—'
  return (q * p).toFixed(2)
}

function openEdit(o: Order) {
  editingId.value = o.id
  editForm.value = {
    delivery_description: o.delivery_description ?? '',
    address_detail: o.address_detail ?? '',
    address_lat: o.address_lat != null ? Number(o.address_lat) : null,
    address_lng: o.address_lng != null ? Number(o.address_lng) : null,
    contact_dongjia_phone: o.contact_dongjia_phone ?? '',
    contact_boss_phone: o.contact_boss_phone ?? '',
    remark: o.remark ?? '',
    internal_notes: o.internal_notes ?? '',
  }
  editLines.value = (o.order_products ?? []).map((p) => ({
    id: p.id,
    product_name_snapshot: p.product_name_snapshot ?? '',
    quantity: String(p.quantity ?? '1'),
    unit_price:
      p.unit_price != null && p.unit_price !== '' ? String(p.unit_price) : '0',
  }))
  showEdit.value = true
}

async function submitEdit() {
  if (editingId.value == null) return
  showLoadingToast({ message: '保存中…', forbidClick: true, duration: 0 })
  try {
    const body: OrderUpdateBody = { ...editForm.value }
    await updateOrder(editingId.value, body)
    for (const line of editLines.value) {
      const name = line.product_name_snapshot.trim()
      if (!name) {
        showFailToast('商品名称不能为空')
        return
      }
      const q = parseInt(line.quantity, 10)
      if (!Number.isFinite(q) || q < 1) {
        showFailToast('数量须为不小于 1 的整数')
        return
      }
      const upRaw = String(line.unit_price).trim()
      const upNum = Number(upRaw === '' ? '0' : upRaw)
      if (!Number.isFinite(upNum)) {
        showFailToast('单价格式不正确')
        return
      }
      await updateOrderProduct(line.id, {
        product_name_snapshot: name,
        quantity: q,
        unit_price: String(upNum),
      })
    }
    showSuccessToast('已保存')
    showEdit.value = false
    await load(true)
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } }
    showFailToast(err.response?.data?.detail || '保存失败')
  } finally {
    closeToast()
  }
}

async function tryCancel(o: Order) {
  if (o.status !== 'PENDING_DISPATCH') return
  try {
    await showConfirmDialog({
      title: '撤销订单',
      message: `确定撤销订单 ${o.order_no}？撤销后不可恢复（货主端将同步）。`,
    })
    showLoadingToast({ message: '处理中…', forbidClick: true })
    await cancelOrder(o.id)
    closeToast()
    showSuccessToast('已撤销')
    await load(true)
  } catch (e) {
    closeToast()
    if (e !== 'cancel') {
      const err = e as { response?: { data?: { detail?: string } } }
      showFailToast(err.response?.data?.detail || '撤销失败')
    }
  }
}

function openRecall(o: Order) {
  if (o.status !== 'ACCEPTED') return
  recallOrderId.value = o.id
  recallReason.value = ''
  showRecall.value = true
}

async function submitRecall() {
  const reason = recallReason.value.trim()
  if (!reason) {
    showFailToast('请填写撤回原因')
    return
  }
  if (recallOrderId.value == null) return
  showLoadingToast({ message: '处理中…', forbidClick: true, duration: 0 })
  try {
    await recallOrder(recallOrderId.value, reason)
    showRecall.value = false
    showSuccessToast('已撤回派单')
    await load(true)
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } }
    showFailToast(err.response?.data?.detail || '撤回失败')
  } finally {
    closeToast()
  }
}
</script>

<template>
  <div class="dispatch-pending role-tool-page">
    <div class="create-strip" role="presentation">
      <div class="create-strip__main" role="button" tabindex="0" @click="goNewDispatcherOrder">
        <div class="create-strip__icon">
          <van-icon name="orders-o" size="22" />
        </div>
        <div class="create-strip__text">
          <span class="create-strip__main-text">新建订单（代货主）</span>
          <span class="create-strip__sub">
            {{
              hasOrderDraft
                ? '左侧空白新单；右侧继续未提交的草稿'
                : '填写送货信息与商品，提交后进入待派单'
            }}
          </span>
        </div>
        <van-icon v-if="!hasOrderDraft" name="arrow" class="create-strip__arrow" />
      </div>
      <button
        v-if="hasOrderDraft"
        type="button"
        class="create-strip__draft-btn"
        aria-label="继续编辑代下单草稿"
        @click.stop="goResumeDispatcherDraft"
      >
        <span class="create-strip__draft-warn"><van-icon name="warning-o" /></span>
        <span class="create-strip__draft-label">继续草稿</span>
      </button>
    </div>

    <van-search v-model="searchText" placeholder="订单号 / 货主 / 地址 / 司机" />

    <van-tabs v-model:active="tabIndex" shrink class="dispatch-pending__tabs">
      <van-tab title="待派单" />
      <van-tab title="运输中" />
    </van-tabs>

    <!-- 固定占位高度，避免「待派单」与「运输中」切换时批量区出现/消失导致内容上跳 -->
    <div class="batch-bar-wrap" :aria-hidden="tabIndex !== 0">
      <div v-show="tabIndex === 0" class="batch-bar">
        <van-button size="small" :type="batchMode ? 'primary' : 'default'" @click="batchMode = !batchMode">
          {{ batchMode ? '取消批量' : '批量派单' }}
        </van-button>
        <van-button
          v-if="batchMode"
          size="small"
          type="primary"
          plain
          :disabled="!selectedIds.length"
          @click="openBatchDispatch"
        >
          为选中订单派单 ({{ selectedIds.length }})
        </van-button>
      </div>
    </div>

    <van-pull-refresh v-model="refreshing" @refresh="onRefresh">
      <van-empty v-if="!loading && !list.length" :description="debouncedQ ? '无匹配订单' : '暂无订单'" />

      <VirtualScrollList v-else :items="list" :estimate-size="280">
        <template #default="{ item }">
          <div
            v-for="o in [ord(item)]"
            :key="o.id"
            class="card"
            :class="{ 'card--batch': batchMode && tabIndex === 0 }"
          >
            <div class="card-top">
              <van-checkbox
                v-if="batchMode && tabIndex === 0 && o.status === 'PENDING_DISPATCH'"
                :model-value="selectedIds.includes(o.id)"
                @update:model-value="(v: boolean) => toggleSelect(o.id, v)"
              />
              <div class="card-title">
                <span class="no">{{ o.order_no }}</span>
                <van-tag :type="orderStatusTagType(o.status)" plain>
                  {{ ORDER_STATUS_LABEL[o.status] }}
                </van-tag>
              </div>
            </div>
            <div class="grid">
              <div class="cell">
                <span class="k">货主</span>
                <span>{{ o.shipper_name || '—' }}</span>
              </div>
              <div class="cell full">
                <span class="k">商品</span>
                <span>{{ productLine(o) }}</span>
              </div>
              <div class="cell full">
                <span class="k">地址</span>
                <span>{{ addrShort(o.address_detail) }}</span>
              </div>
              <div class="cell">
                <span class="k">下单时间</span>
                <span>{{ fmtTime(o.created_at) }}</span>
              </div>
              <div v-if="o.driver_name" class="cell">
                <span class="k">司机</span>
                <span>{{ o.driver_name }}</span>
              </div>
            </div>
            <div class="actions">
              <template v-if="o.status === 'PENDING_DISPATCH'">
                <van-button size="small" type="primary" @click="openDispatchSingle(o)">派单</van-button>
                <van-button size="small" plain @click="openEdit(o)">编辑</van-button>
                <van-button size="small" plain type="danger" @click="tryCancel(o)">撤销订单</van-button>
              </template>
              <template v-else-if="o.status === 'ACCEPTED'">
                <van-button size="small" type="warning" plain @click="openRecall(o)">撤回派单</van-button>
                <van-button size="small" plain @click="openEdit(o)">编辑</van-button>
              </template>
            </div>
          </div>
        </template>
      </VirtualScrollList>
    </van-pull-refresh>

    <van-popup v-model:show="showDispatch" position="bottom" round class="dispatch-popup">
      <div class="popup-title">{{ dispatchBatch ? '批量派单' : '派单' }}</div>
      <van-field
        :model-value="selectedDriverLabel"
        label="司机"
        readonly
        is-link
        placeholder="请选择司机"
        @click="pickDriverVisible = true"
      />
      <div class="remark-hp-block remark-hp-block--popup">
        <div class="hp-row">
          <div class="hp-label">内部备注</div>
          <div class="hp-main">
            <van-field
              v-model="dispatchNote"
              type="textarea"
              rows="2"
              autosize
              placeholder="追加备注（确定派单时写入内部备注）"
              maxlength="4000"
              class="note-field-flat"
            />
          </div>
        </div>
      </div>
      <div class="popup-actions">
        <van-button block type="primary" :disabled="!dispatchDriverId" @click="submitDispatch">
          确定
        </van-button>
        <van-button block plain @click="showDispatch = false">取消</van-button>
      </div>
    </van-popup>

    <van-popup v-model:show="pickDriverVisible" position="bottom" round>
      <van-nav-bar title="选择司机" left-text="关闭" @click-left="pickDriverVisible = false" />
      <van-cell-group>
        <van-cell
          v-for="d in drivers"
          :key="d.id"
          :title="d.full_name || '未命名'"
          :label="d.phone"
          clickable
          @click="pickDriver(d.id)"
        />
      </van-cell-group>
    </van-popup>

    <van-popup v-model:show="showEdit" position="bottom" round :style="{ height: '85%' }">
      <div class="popup-title">编辑订单</div>
      <van-form @submit="submitEdit">
        <div v-if="editLines.length" class="edit-lines-wrap">
          <div class="edit-lines-wrap__heading">商品明细</div>
          <div
            v-for="(line, idx) in editLines"
            :key="line.id"
            class="edit-line-block"
          >
            <div class="edit-line-block__title">商品 {{ idx + 1 }}</div>
            <van-field
              v-model="line.product_name_snapshot"
              label="商品名称"
              placeholder="名称"
              maxlength="256"
            />
            <van-field v-model="line.quantity" label="数量" type="digit" placeholder="1" />
            <van-field v-model="line.unit_price" label="单价" placeholder="0" />
            <div class="edit-line-block__sub">小计 {{ fmtLineSub(line) }} 元（数量×单价）</div>
          </div>
        </div>
        <p v-else class="edit-lines-hint">当前订单无商品明细行，可仅编辑下方「商品说明」等字段。</p>
        <van-field v-model="editForm.delivery_description" label="商品说明" type="textarea" rows="2" />
        <van-field v-model="editForm.address_detail" label="地址" type="textarea" rows="2" />
        <div class="map-row">
          <van-button size="small" type="primary" icon="location-o" @click="showMapEdit = true">
            地图选点
          </van-button>
        </div>
        <van-field v-model="editForm.contact_dongjia_phone" label="东家电话" />
        <van-field v-model="editForm.contact_boss_phone" label="老板电话" />
        <div class="remark-hp-block remark-hp-block--edit">
          <div class="hp-row">
            <div class="hp-label">内部备注</div>
            <div class="hp-main">
              <van-field
                v-model="editForm.internal_notes"
                type="textarea"
                rows="3"
                autosize
                placeholder="追加备注（点「保存」时写入）"
                maxlength="4000"
                class="note-field-flat"
              />
            </div>
          </div>
        </div>
        <van-field v-model="editForm.remark" label="备注" type="textarea" rows="2" />
        <div style="padding: 12px">
          <van-button block type="primary" native-type="submit">保存</van-button>
          <van-button block plain style="margin-top: 8px" @click="showEdit = false">取消</van-button>
        </div>
      </van-form>
    </van-popup>

    <AmapPicker
      v-model:show="showMapEdit"
      :initial-lng-lat="initialEditLngLat"
      panel-title="编辑送货地址"
      @confirm="onEditMapConfirm"
    />

    <van-popup v-model:show="showRecall" position="bottom" round class="recall-popup">
      <div class="popup-title">撤回派单</div>
      <van-field
        v-model="recallReason"
        type="textarea"
        rows="3"
        placeholder="请填写撤回原因（记入操作日志与订单快照）"
        maxlength="1024"
      />
      <div class="popup-actions">
        <van-button block type="primary" @click="submitRecall">确定撤回</van-button>
        <van-button block plain @click="showRecall = false">取消</van-button>
      </div>
    </van-popup>
  </div>
</template>

<style scoped>
.dispatch-pending {
  padding-bottom: 8px;
}

.edit-lines-wrap {
  margin: 0 12px 8px;
  padding: 8px 0 4px;
  border-bottom: 1px solid var(--van-border-color);
}
.edit-lines-wrap__heading {
  font-size: 14px;
  font-weight: 600;
  padding: 4px 4px 8px;
  color: var(--van-text-color);
}
.edit-line-block {
  padding-bottom: 8px;
  margin-bottom: 8px;
  border-bottom: 1px dashed var(--van-border-color);
}
.edit-line-block:last-of-type {
  border-bottom: none;
  margin-bottom: 0;
}
.edit-line-block__title {
  font-size: 12px;
  font-weight: 600;
  padding: 4px 4px 0;
  color: var(--van-text-color-2);
}
.edit-line-block__sub {
  font-size: 12px;
  color: var(--van-text-color-2);
  padding: 0 16px 4px;
  text-align: right;
}
.edit-lines-hint {
  margin: 8px 16px 12px;
  font-size: 12px;
  line-height: 1.5;
  color: var(--van-text-color-3);
}

.create-strip {
  display: flex;
  align-items: stretch;
  margin: 8px 12px 4px;
  background: var(--van-background-2, #fff);
  border: 1px solid var(--van-border-color);
  border-radius: var(--van-radius-lg, 12px);
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.05);
  overflow: hidden;
}
.create-strip__main {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  padding: 12px 10px 12px 12px;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}
.create-strip__main:active {
  background: var(--van-active-color);
}
.create-strip__icon {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 44px;
  height: 44px;
  border-radius: 10px;
  background: rgba(22, 119, 255, 0.1);
  color: var(--van-primary-color, #1677ff);
}
.create-strip__text {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.create-strip__main-text {
  font-size: 16px;
  font-weight: 600;
  color: var(--van-text-color);
}
.create-strip__sub {
  font-size: 12px;
  line-height: 1.45;
  color: var(--van-text-color-2);
}
.create-strip__arrow {
  flex-shrink: 0;
  color: var(--van-text-color-3);
  font-size: 16px;
}
.create-strip__draft-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  width: 72px;
  flex-shrink: 0;
  margin: 0;
  padding: 10px 8px;
  border: none;
  border-left: 1px solid var(--van-border-color);
  background: rgba(238, 10, 36, 0.06);
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
  font: inherit;
  color: var(--van-text-color);
}
.create-strip__draft-btn:active {
  background: rgba(238, 10, 36, 0.12);
}
.create-strip__draft-warn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  font-size: 18px;
  color: #ee0a24;
  background: #fff;
  border-radius: 50%;
  box-shadow: 0 0 0 1px rgba(238, 10, 36, 0.2);
}
.create-strip__draft-label {
  font-size: 11px;
  font-weight: 600;
  line-height: 1.2;
  color: #ee0a24;
  text-align: center;
}

.dispatch-pending__tabs {
  margin-top: 0;
}

.dispatch-pending__tabs :deep(.van-tabs__wrap) {
  min-height: 44px;
}

.batch-bar-wrap {
  min-height: 48px;
  box-sizing: border-box;
}

.batch-bar {
  display: flex;
  gap: 8px;
  padding: 8px 12px;
  flex-wrap: wrap;
}
.card {
  margin: 8px 12px;
  padding: 11px 12px;
  background: var(--van-background-2, #fff);
  border: 1px solid var(--van-border-color);
  border-radius: var(--van-radius-lg, 12px);
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.05);
}
.card--batch {
  padding-left: 8px;
}
.card-top {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-bottom: 8px;
}
.card-title {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.no {
  font-weight: 600;
  font-size: 16px;
  color: var(--van-text-color);
}
.grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px 12px;
  font-size: 13px;
}
.cell {
  display: flex;
  gap: 6px;
}
.cell.full {
  grid-column: 1 / -1;
}
.k {
  color: var(--van-text-color-2, #646566);
  flex-shrink: 0;
  width: 4em;
}
.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
  justify-content: flex-end;
}
.popup-title {
  font-weight: 600;
  margin-bottom: 12px;
  text-align: center;
}
.remark-hp-block {
  padding: 4px 0 8px;
}
.remark-hp-block--popup {
  margin-top: 4px;
  padding-top: 12px;
  border-top: 1px solid var(--van-border-color, #ebedf0);
}
.remark-hp-block--edit {
  padding-left: 16px;
  padding-right: 16px;
  margin-top: 4px;
  padding-top: 10px;
  border-top: 1px solid var(--van-border-color, #ebedf0);
}
.hp-row {
  display: flex;
  flex-direction: row;
  align-items: flex-start;
  gap: 10px;
}
.hp-label {
  flex-shrink: 0;
  width: 72px;
  font-size: 13px;
  color: var(--van-text-color-2, #646566);
  line-height: 1.35;
  padding-top: 10px;
}
.hp-main {
  flex: 1;
  min-width: 0;
}
.note-field-flat {
  padding-left: 0 !important;
  padding-right: 0 !important;
}
.popup-actions {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.dispatch-popup {
  padding: 16px;
}
.recall-popup {
  padding: 16px;
}
.map-row {
  padding: 8px 16px;
}
</style>
