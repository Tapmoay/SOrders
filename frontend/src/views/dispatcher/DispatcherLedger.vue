<script setup lang="ts">
import { showConfirmDialog, showFailToast, showSuccessToast, showToast } from 'vant'
import { computed, onMounted, ref, watch } from 'vue'

import LedgerEntryTable from '@/components/LedgerEntryTable.vue'
import {
  createLedgerEntry,
  createLedgerExportJob,
  deleteLedgerEntry,
  fetchLedgerEntries,
  fetchTempShipperNames,
  syncLedgerFromDeliveredOrders,
  updateLedgerEntry,
  type LedgerEntry,
  type ExportFormat,
} from '@/api/ledger'
import { fetchOrders } from '@/api/orders'
import { fetchProductsCatalog, type Product } from '@/api/products'
import { fetchUsers, type UserListItem } from '@/api/user'
import { ORDER_STATUS_LABEL } from '@/constants/order'
import type { Order, OrderProduct } from '@/types/order'
import { formatApiError } from '@/utils/apiError'
import { formatMoney2 } from '@/utils/formatMoney'

function pad(n: number) {
  return String(n).padStart(2, '0')
}
function todayStr() {
  const d = new Date()
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}
function firstDayOfMonthStr() {
  const d = new Date()
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-01`
}
/** 近一年（用于默认导出区间） */
function oneYearAgoStr() {
  const d = new Date()
  d.setDate(d.getDate() - 365)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

const pick = ref(false)
const shipperSearch = ref('')
const shippers = ref<UserListItem[]>([])
const shipperId = ref<number | null>(null)
/** 与 shipperId 互斥：按临时货主称呼查账本 */
const ledgerTempName = ref('')
const showTempLedgerDialog = ref(false)
const tempLedgerInput = ref('')
/** 留空表示不按该侧筛选，便于查看历史全部记录 */
const dateFrom = ref('')
const dateTo = ref('')
const list = ref<LedgerEntry[]>([])
const loading = ref(false)

const showManual = ref(false)
/** 非空表示编辑已有行；空表示新建手动账项 */
const editingLedgerEntryId = ref<number | null>(null)
const manualForm = ref({
  entry_date: todayStr(),
  product_id: null as number | null,
  product_name: '',
  quantity: '1',
  unit_price: '',
  note: '',
  order_id: null as number | null,
})
const savingManual = ref(false)

const productsCatalog = ref<Product[]>([])
const shipperOrders = ref<Order[]>([])
/** 曾出现的临时货主称呼（后端汇总），用于快捷筛选 */
const tempShipperNames = ref<string[]>([])
const showProductPick = ref(false)
const showOrderPick = ref(false)
const productSearch = ref('')
const orderSearch = ref('')
const showEntryCal = ref(false)
const calendarMin = new Date(2020, 0, 1)
const calendarMax = new Date(2035, 11, 31)

const manualLineTotal = computed(() => {
  const qty = Number.parseInt(manualForm.value.quantity, 10)
  const up = Number(manualForm.value.unit_price)
  if (!Number.isFinite(qty) || qty < 1 || !Number.isFinite(up)) return '—'
  return formatMoney2(qty * up)
})

const productPickLabel = computed(() =>
  manualForm.value.product_name.trim() ? manualForm.value.product_name : '请选择商品',
)

const orderPickLabel = computed(() => {
  const id = manualForm.value.order_id
  if (id == null) return '不关联订单'
  const o = shipperOrders.value.find((x) => x.id === id)
  return o
    ? `${o.order_no} · ${o.order_date} · ${ORDER_STATUS_LABEL[o.status]}`
    : `订单 #${id}`
})

const filteredProducts = computed(() => {
  const q = productSearch.value.trim().toLowerCase()
  let list = productsCatalog.value
  if (q) {
    list = list.filter((p) => p.name.toLowerCase().includes(q))
  }
  return [...list].sort((a, b) => {
    if (a.is_active !== b.is_active) return a.is_active ? -1 : 1
    return a.name.localeCompare(b.name, 'zh-CN')
  })
})

const filteredShipperOrders = computed(() => {
  const q = orderSearch.value.trim().toLowerCase()
  let list = shipperOrders.value
  if (q) {
    list = list.filter(
      (o) =>
        o.order_no.toLowerCase().includes(q) ||
        (o.address_detail || '').toLowerCase().includes(q),
    )
  }
  return list
})

function resetManualForm() {
  manualForm.value = {
    entry_date: todayStr(),
    product_id: null,
    product_name: '',
    quantity: '1',
    unit_price: '',
    note: '',
    order_id: null,
  }
  editingLedgerEntryId.value = null
  productSearch.value = ''
  orderSearch.value = ''
}

async function loadManualPickersData() {
  const sid = shipperId.value
  const tn = ledgerTempName.value.trim()
  if (!sid && !tn) return
  try {
    const [plist, olist] = await Promise.all([
      fetchProductsCatalog(),
      sid
        ? fetchOrders(undefined, undefined, sid)
        : fetchOrders(undefined, undefined, null, tn),
    ])
    productsCatalog.value = plist
    shipperOrders.value = olist
  } catch (e: unknown) {
    showFailToast(formatApiError(e, '加载商品或订单列表失败'))
  }
}

function openManualCreate() {
  if (!shipperId.value && !ledgerTempName.value.trim()) return
  resetManualForm()
  showManual.value = true
}

function onPickProduct(p: Product) {
  if (!p.is_active) {
    showFailToast('该商品已下架，请选其他商品或先上架')
    return
  }
  manualForm.value.product_id = p.id
  manualForm.value.product_name = p.name
  manualForm.value.unit_price = String(p.default_unit_price)
  showProductPick.value = false
}

/** 业务日期：已送达用送达日，否则用下单日 */
function entryDateFromOrder(o: Order): string {
  if (o.delivered_at) {
    return o.delivered_at.slice(0, 10)
  }
  return o.order_date.slice(0, 10)
}

/** 按订单明细匹配上架商品；单价始终用订单行金额（与订单一致） */
function resolveProductFromOrderLine(line: OrderProduct): {
  product_id: number | null
  product_name: string
  unit_price: string
} {
  const unitPrice = String(line.unit_price)
  const snap = (line.product_name_snapshot || '').trim()
  if (line.product_id != null) {
    const cat = productsCatalog.value.find((p) => p.id === line.product_id)
    if (cat?.is_active) {
      return { product_id: cat.id, product_name: cat.name, unit_price: unitPrice }
    }
  }
  const byName = productsCatalog.value.find((p) => p.is_active && p.name.trim() === snap)
  if (byName) {
    return { product_id: byName.id, product_name: byName.name, unit_price: unitPrice }
  }
  return { product_id: null, product_name: snap, unit_price: unitPrice }
}

function applyOrderToManualForm(o: Order) {
  manualForm.value.entry_date = entryDateFromOrder(o)
  manualForm.value.note = (o.remark || '').trim()

  const lines = o.order_products || []
  if (lines.length === 0) {
    manualForm.value.product_id = null
    manualForm.value.product_name = ''
    manualForm.value.quantity = '1'
    manualForm.value.unit_price = ''
    showToast('该订单暂无商品明细，请手动选择商品并填写')
    return
  }

  const line = lines[0]
  const resolved = resolveProductFromOrderLine(line)
  manualForm.value.product_id = resolved.product_id
  manualForm.value.product_name = resolved.product_name
  manualForm.value.quantity = String(line.quantity)
  manualForm.value.unit_price = resolved.unit_price

  if (resolved.product_id == null && resolved.product_name) {
    showToast(
      lines.length > 1
        ? '已带入首条明细；未匹配到上架商品，请从商品库选择'
        : '未自动匹配到上架商品，名称已带入，请从商品库点选商品',
    )
  } else if (lines.length > 1) {
    showToast('该订单含多条商品明细，已带入第一条，可继续修改')
  }
}

function onPickOrder(o: Order | null) {
  if (!o) {
    manualForm.value.order_id = null
    showOrderPick.value = false
    return
  }
  manualForm.value.order_id = o.id
  applyOrderToManualForm(o)
  showOrderPick.value = false
}

function onEntryCalendarConfirm(val: Date | Date[]) {
  const d = Array.isArray(val) ? val[0] : val
  if (!d || Number.isNaN(d.getTime())) return
  const y = d.getFullYear()
  const m = pad(d.getMonth() + 1)
  const day = pad(d.getDate())
  manualForm.value.entry_date = `${y}-${m}-${day}`
  showEntryCal.value = false
}

watch(showManual, (v) => {
  if (v && (shipperId.value || ledgerTempName.value.trim())) void loadManualPickersData()
})

watch(pick, (v) => {
  if (v) void loadTempShipperNames()
})

const exportFmt = ref<ExportFormat>('excel')
const exporting = ref(false)

const filteredShippers = computed(() => {
  const q = shipperSearch.value.trim().toLowerCase()
  if (!q) return shippers.value
  return shippers.value.filter((s) => {
    const name = (s.full_name || '').toLowerCase()
    const phone = (s.phone || '').toLowerCase()
    return name.includes(q) || phone.includes(q)
  })
})

const shipperLabel = computed(() => {
  if (shipperId.value != null) {
    const s = shippers.value.find((x) => x.id === shipperId.value)
    return s ? `${s.full_name || s.phone}` : ''
  }
  const t = ledgerTempName.value.trim()
  return t ? `临时：${t}` : ''
})

/** 当前列表汇总（与后端筛选一致） */
const stats = computed(() => {
  let sum = 0
  let auto = 0
  let manual = 0
  for (const r of list.value) {
    const t = Number(r.total)
    if (!Number.isNaN(t)) sum += t
    if (r.source === 'order') auto += 1
    else manual += 1
  }
  return {
    count: list.value.length,
    sum,
    auto,
    manual,
  }
})

function presetDateUnlimited() {
  dateFrom.value = ''
  dateTo.value = ''
}

function presetDateThisMonth() {
  dateFrom.value = firstDayOfMonthStr()
  dateTo.value = todayStr()
}

function presetDateLastYear() {
  dateFrom.value = oneYearAgoStr()
  dateTo.value = todayStr()
}

async function loadShippers() {
  try {
    shippers.value = await fetchUsers({ role: 'shipper' })
  } catch (e: unknown) {
    showFailToast(formatApiError(e, '加载货主列表失败'))
  }
}

async function loadTempShipperNames() {
  try {
    tempShipperNames.value = await fetchTempShipperNames()
  } catch {
    /* 列表为增强能力，失败不阻断账本页 */
  }
}

function selectTempNameChip(name: string) {
  const t = name.trim()
  if (!t) return
  shipperId.value = null
  ledgerTempName.value = t
  pick.value = false
  shipperSearch.value = ''
}

async function loadEntries(opts?: { syncFromOrders?: boolean }) {
  const sid = shipperId.value
  const tn = ledgerTempName.value.trim()
  if (!sid && !tn) {
    list.value = []
    return
  }
  loading.value = true
  try {
    if (opts?.syncFromOrders) {
      try {
        await syncLedgerFromDeliveredOrders(
          sid ? { shipper_id: sid } : { temp_shipper_name: tn },
        )
      } catch (e: unknown) {
        showFailToast(formatApiError(e, '从订单同步账本失败'))
      }
    }
    list.value = await fetchLedgerEntries({
      ...(sid ? { shipper_id: sid } : { temp_shipper_name: tn }),
      date_from: dateFrom.value || undefined,
      date_to: dateTo.value || undefined,
    })
  } catch (e: unknown) {
    showFailToast(formatApiError(e, '加载失败'))
  } finally {
    loading.value = false
  }
}

watch([shipperId, ledgerTempName], () => {
  if (!shipperId.value && !ledgerTempName.value.trim()) {
    list.value = []
    return
  }
  void loadEntries({ syncFromOrders: true })
})

watch([dateFrom, dateTo], () => {
  if (!shipperId.value && !ledgerTempName.value.trim()) return
  void loadEntries()
})

function selectShipper(s: UserListItem) {
  shipperId.value = s.id
  ledgerTempName.value = ''
  pick.value = false
  shipperSearch.value = ''
}

function openTempLedgerDialog() {
  tempLedgerInput.value = ledgerTempName.value.trim()
  showTempLedgerDialog.value = true
}

function confirmTempLedger() {
  const t = tempLedgerInput.value.trim()
  if (!t) {
    showFailToast('请输入临时货主名称')
    return
  }
  shipperId.value = null
  ledgerTempName.value = t
  showTempLedgerDialog.value = false
  pick.value = false
  shipperSearch.value = ''
}

function openEdit(row: LedgerEntry) {
  editingLedgerEntryId.value = row.id
  manualForm.value = {
    entry_date: row.entry_date.slice(0, 10),
    product_id: row.product_id ?? null,
    product_name: row.product_name,
    quantity: String(row.quantity),
    unit_price: String(row.unit_price),
    note: row.note || '',
    order_id: row.order_id ?? null,
  }
  showManual.value = true
}

async function saveManual() {
  const sid = shipperId.value
  const tn = ledgerTempName.value.trim()
  if (!sid && !tn) return
  if (manualForm.value.product_id == null) {
    showFailToast('请从商品库选择商品')
    return
  }
  const name = manualForm.value.product_name.trim()
  if (!name) {
    showFailToast('请选择有效商品')
    return
  }
  const qty = Number.parseInt(manualForm.value.quantity, 10)
  if (!Number.isFinite(qty) || qty < 1) {
    showFailToast('请输入有效数量')
    return
  }
  const up = Number(manualForm.value.unit_price)
  if (!Number.isFinite(up)) {
    showFailToast('请输入有效单价')
    return
  }
  const total = up * qty

  savingManual.value = true
  try {
    const oid = manualForm.value.order_id
    const pid = manualForm.value.product_id
    if (editingLedgerEntryId.value != null) {
      await updateLedgerEntry(editingLedgerEntryId.value, {
        entry_date: manualForm.value.entry_date,
        product_name: name,
        quantity: qty,
        unit_price: up,
        total,
        note: manualForm.value.note,
        order_id: oid,
        product_id: pid,
      })
      showSuccessToast('已保存')
    } else {
      await createLedgerEntry({
        ...(sid ? { shipper_id: sid } : { temp_shipper_name: tn }),
        entry_date: manualForm.value.entry_date,
        product_name: name,
        quantity: qty,
        unit_price: up,
        total,
        source: 'manual',
        note: manualForm.value.note,
        order_id: oid ?? undefined,
        product_id: pid ?? undefined,
      })
      showSuccessToast('已添加')
    }
    showManual.value = false
    await loadEntries({ syncFromOrders: false })
  } catch (e: unknown) {
    showFailToast(formatApiError(e, '保存失败'))
  } finally {
    savingManual.value = false
  }
}

async function tryDelete(row: LedgerEntry) {
  try {
    await showConfirmDialog({ title: '删除', message: '确定删除该条记录？' })
    await deleteLedgerEntry(row.id)
    showSuccessToast('已删除')
    await loadEntries({ syncFromOrders: false })
  } catch (e) {
    if (e !== 'cancel') showFailToast('删除失败')
  }
}

async function runExport() {
  if (ledgerTempName.value.trim()) {
    showFailToast('临时货主账本暂不支持导出，请使用系统货主账号')
    return
  }
  if (!shipperId.value) {
    showFailToast('请先选择货主')
    return
  }
  let df = dateFrom.value.trim()
  let dt = dateTo.value.trim()
  if (!df || !dt) {
    df = oneYearAgoStr()
    dt = todayStr()
    showToast('未填写导出日期，已按近一年区间提交')
  }
  exporting.value = true
  try {
    await createLedgerExportJob({
      shipper_id: shipperId.value,
      date_from: df,
      date_to: dt,
      export_format: exportFmt.value,
    })
    showSuccessToast('导出任务已在后台执行，完成后请在消息中心查看下载链接')
  } catch (e: unknown) {
    showFailToast(formatApiError(e, '提交失败'))
  } finally {
    exporting.value = false
  }
}

onMounted(() => {
  void loadShippers()
  void loadTempShipperNames()
})
</script>

<template>
  <div class="led role-tool-page ledger-page">
    <van-notice-bar
      wrapable
      :scrollable="false"
      left-icon="info-o"
      class="ledger-notice"
      text="订单送达时即按明细自动入账（含临时货主订单）；本页用于按货主/称呼筛选查看，并非手动「创建账本」。可用手动记账补录。货主仅可查看。编辑账项时订单来源行会同步回订单明细。点击订单号可查看订单。"
    />

    <van-cell-group inset title="筛选" class="ledger-block">
      <van-popover
        v-model:show="pick"
        placement="bottom-start"
        :offset="[0, 8]"
        :show-arrow="true"
        theme="light"
        class="ledger-shipper-popover"
        teleport="body"
        overlay
        close-on-click-overlay
        :overlay-style="{ background: 'rgba(0, 0, 0, 0.35)' }"
        :close-on-click-outside="true"
      >
        <template #reference>
          <van-field
            label="货主"
            readonly
            is-link
            :model-value="shipperLabel"
            placeholder="点击选择货主"
          />
        </template>
        <div class="ledger-shipper-float">
          <div class="ledger-shipper-float__head">选择货主</div>
          <van-search v-model="shipperSearch" placeholder="搜索姓名或手机号" />
          <div v-if="tempShipperNames.length" class="ledger-temp-chips">
            <div class="ledger-temp-chips__label">临时称呼（已自动入账，点此查看）</div>
            <div class="ledger-temp-chips__row">
              <van-tag
                v-for="n in tempShipperNames"
                :key="n"
                plain
                type="primary"
                size="medium"
                @click="selectTempNameChip(n)"
              >
                {{ n }}
              </van-tag>
            </div>
          </div>
          <div class="ledger-shipper-float__scroll">
            <van-cell
              title="临时货主（记名）"
              label="无系统账号；送达时已自动入账，在此输入称呼或选上方标签"
              is-link
              @click="openTempLedgerDialog"
            />
            <van-empty
              v-if="!filteredShippers.length"
              image="search"
              description="无匹配已注册货主"
            />
            <van-cell
              v-for="s in filteredShippers"
              :key="s.id"
              :title="s.full_name || s.phone"
              :label="s.phone && s.full_name ? s.phone : ''"
              clickable
              @click="selectShipper(s)"
            />
          </div>
        </div>
      </van-popover>
      <van-field v-model="dateFrom" label="开始日期" placeholder="留空=不限制" />
      <van-field v-model="dateTo" label="结束日期" placeholder="留空=不限制" />
      <div class="ledger-presets">
        <van-button size="small" plain type="primary" @click="presetDateUnlimited">不限日期</van-button>
        <van-button size="small" plain type="primary" @click="presetDateThisMonth">本月</van-button>
        <van-button size="small" plain type="primary" @click="presetDateLastYear">近一年</van-button>
      </div>
      <div class="ledger-hint">提示：起止都留空时查询该货主全部账本。若曾只筛「本月」，历史月份入账会被挡住。</div>
    </van-cell-group>

    <div class="ledger-toolbar">
      <van-button
        type="primary"
        size="small"
        round
        :disabled="!shipperId && !ledgerTempName.trim()"
        @click="loadEntries({ syncFromOrders: true })"
      >
        刷新列表
      </van-button>
      <div class="ledger-toolbar__export">
        <span class="ledger-toolbar__label">导出格式</span>
        <van-radio-group v-model="exportFmt" direction="horizontal" class="ledger-radio">
          <van-radio name="excel">Excel</van-radio>
          <van-radio name="pdf">PDF</van-radio>
        </van-radio-group>
        <van-button
          type="primary"
          size="small"
          plain
          round
          :loading="exporting"
          :disabled="!shipperId || !!ledgerTempName.trim()"
          @click="runExport"
        >
          导出
        </van-button>
      </div>
    </div>

    <van-loading v-if="loading" vertical class="ledger-loading">加载中…</van-loading>

    <template v-else>
      <van-empty
        v-if="!shipperId && !ledgerTempName.trim()"
        image="search"
        description="请先选择已注册货主或临时货主，再查看账本"
      />
      <template v-else>
        <van-cell-group inset title="统计（当前筛选）" class="ledger-stats">
          <van-cell title="记录条数" :value="String(stats.count)" />
          <van-cell title="金额合计（元）" :value="formatMoney2(stats.sum)" />
          <van-cell title="自动记账 / 手动" :value="`${stats.auto} / ${stats.manual}`" />
        </van-cell-group>
        <div class="ledger-manual-bar">
          <van-button type="primary" block round :disabled="loading" @click="openManualCreate">
            手动记账
          </van-button>
        </div>
        <van-empty
          v-if="!list.length"
          image="default"
          description="该筛选条件下暂无记录。可点击「手动记账」补录，或等待订单送达自动入账。"
        />
        <LedgerEntryTable
          v-if="list.length"
          :entries="list"
          :read-only="false"
          order-route-name="dispatcher-order-detail"
          @edit="openEdit"
          @delete="tryDelete"
        />
      </template>
    </template>

    <van-popup
      v-model:show="showTempLedgerDialog"
      position="bottom"
      round
      teleport="body"
      :style="{ padding: '16px', paddingBottom: 'max(16px, env(safe-area-inset-bottom))' }"
    >
      <div class="ledger-popup-title">查看临时货主账本</div>
      <p class="ledger-temp-dialog-tip">
        订单送达时已按明细自动入账。请输入与代下单时一致的称呼以筛选记录。
      </p>
      <van-field v-model="tempLedgerInput" label="称呼" placeholder="与代下单时填写的临时货主一致" />
      <div class="ledger-temp-dialog-actions">
        <van-button block round @click="showTempLedgerDialog = false">取消</van-button>
        <van-button block round type="primary" @click="confirmTempLedger">确定</van-button>
      </div>
    </van-popup>

    <van-popup
      v-model:show="showManual"
      position="bottom"
      round
      :style="{ padding: '16px', maxHeight: '85vh' }"
      class="ledger-manual-popup"
      teleport="body"
      @closed="resetManualForm"
    >
      <div class="ledger-popup-title">{{ editingLedgerEntryId != null ? '编辑账项' : '手动记账' }}</div>
      <van-field
        label="业务日期"
        readonly
        is-link
        :model-value="manualForm.entry_date"
        placeholder="选择日期"
        @click="showEntryCal = true"
      />
      <van-field
        label="关联订单"
        readonly
        is-link
        :model-value="orderPickLabel"
        placeholder="从历史订单选择"
        @click="showOrderPick = true"
      />
      <!-- ⚠️ 如实说明（2026-09-19 审计）：手工记账**不会挂到订单上** ——
           后端刻意把 `order_id` 置空（挂了会被当日订单账重复计入），只把它记进审计日志当线索。
           原来这一格叫「关联订单」、选完还显示单号，用户会以为这笔账挂到了那张单上。 -->
      <p v-if="manualForm.order_id != null" class="manual-order-hint">
        手工记账不会挂到订单上（订单账由送达/货损自动生成，挂了会重复计入）。
        这里选的单号只写进审计日志，方便日后查这笔钱的来由。
      </p>
      <van-field
        label="商品"
        readonly
        is-link
        :model-value="productPickLabel"
        placeholder="从商品库选择"
        @click="showProductPick = true"
      />
      <van-field v-model="manualForm.quantity" label="数量" type="digit" placeholder="正整数" />
      <van-field v-model="manualForm.unit_price" label="单价（元）" type="number" placeholder="可修改" />
      <van-field label="总价（元）" readonly :model-value="manualLineTotal">
        <template #extra>
          <span class="ledger-auto-hint">自动</span>
        </template>
      </van-field>
      <van-field v-model="manualForm.note" label="备注" type="textarea" rows="2" autosize placeholder="选填" />
      <van-button block type="primary" round :loading="savingManual" @click="saveManual">保存</van-button>
    </van-popup>

    <van-calendar
      v-model:show="showEntryCal"
      type="single"
      :min-date="calendarMin"
      :max-date="calendarMax"
      @confirm="onEntryCalendarConfirm"
    />

    <van-popup
      v-model:show="showProductPick"
      position="bottom"
      round
      teleport="body"
      :style="{ height: '62vh' }"
      class="ledger-sub-popup"
    >
      <div class="ledger-sub-popup__head">选择商品</div>
      <van-search v-model="productSearch" placeholder="搜索商品名称" />
      <div class="ledger-sub-popup__scroll">
        <van-empty v-if="!filteredProducts.length" description="无匹配商品" />
        <van-cell
          v-for="p in filteredProducts"
          :key="p.id"
          :title="p.name"
          :label="p.is_active ? `默认单价 ¥${formatMoney2(p.default_unit_price)}` : '已下架'"
          clickable
          :class="{ 'is-disabled': !p.is_active }"
          @click="p.is_active ? onPickProduct(p) : showFailToast('该商品已下架')"
        />
      </div>
    </van-popup>

    <van-popup
      v-model:show="showOrderPick"
      position="bottom"
      round
      teleport="body"
      :style="{ height: '62vh' }"
      class="ledger-sub-popup"
    >
      <div class="ledger-sub-popup__head">关联历史订单</div>
      <van-search v-model="orderSearch" placeholder="搜索订单号或地址" />
      <div class="ledger-sub-popup__scroll">
        <van-cell title="不关联订单" clickable @click="onPickOrder(null)" />
        <van-empty v-if="!filteredShipperOrders.length" description="暂无订单" />
        <van-cell
          v-for="o in filteredShipperOrders"
          :key="o.id"
          :title="o.order_no"
          :label="`${o.order_date} · ${ORDER_STATUS_LABEL[o.status]}`"
          clickable
          @click="onPickOrder(o)"
        />
      </div>
    </van-popup>

  </div>
</template>

<style scoped>
/* 手工记账的「关联订单」说明：这一格**不会**把账挂到订单上（后端刻意置空，防重复计入） */
.manual-order-hint {
  margin: 6px 16px 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--van-text-color-2, #646566);
}
.ledger-page {
  padding-bottom: 24px;
}

.ledger-notice {
  margin: 8px 12px 0;
  border-radius: 8px;
}

.ledger-block {
  margin-top: 12px;
}

.ledger-presets {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 8px 16px 4px;
}

.ledger-hint {
  padding: 0 16px 12px;
  font-size: 12px;
  line-height: 1.5;
  color: var(--van-text-color-2);
}

.ledger-manual-bar {
  margin: 0 16px 12px;
}

.ledger-stats {
  margin: 0 0 12px;
}

.ledger-stats :deep(.van-cell__value) {
  font-weight: 600;
  color: var(--van-primary-color, #1677ff);
}

.ledger-toolbar {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin: 12px 16px 16px;
  padding: 12px;
  background: var(--van-background-2, #f7f8fa);
  border-radius: 12px;
  border: 1px solid var(--van-border-color);
}

.ledger-toolbar__export {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
  padding-top: 4px;
  border-top: 1px dashed var(--van-border-color);
}

.ledger-toolbar__label {
  font-size: 12px;
  color: var(--van-text-color-2);
  width: 100%;
}

.ledger-radio {
  flex: 1;
  min-width: 0;
}

.ledger-loading {
  padding: 48px 0;
}

.ledger-shipper-popover :deep(.van-popover__content) {
  padding: 0;
}

.ledger-shipper-float {
  display: flex;
  flex-direction: column;
  width: min(88vw, 360px);
  max-height: min(65vh, 400px);
  overflow: hidden;
  border-radius: 12px;
  background: var(--van-background-2, #fff);
  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.08);
}

.ledger-shipper-float__head {
  flex-shrink: 0;
  padding: 10px 16px 6px;
  font-size: 15px;
  font-weight: 600;
  color: var(--van-text-color);
}

.ledger-shipper-float :deep(.van-search) {
  padding: 4px 8px 8px;
}

.ledger-temp-chips {
  flex-shrink: 0;
  padding: 0 12px 10px;
  border-bottom: 1px solid var(--van-border-color);
}
.ledger-temp-chips__label {
  font-size: 12px;
  color: var(--van-text-color-2);
  margin-bottom: 6px;
}
.ledger-temp-chips__row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.ledger-temp-dialog-tip {
  font-size: 13px;
  line-height: 1.5;
  color: var(--van-text-color-2);
  margin: -4px 0 12px;
}

.ledger-shipper-float__scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
}

.ledger-shipper-float__scroll :deep(.van-empty) {
  padding: 16px 0 24px;
}

.ledger-popup-title {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 12px;
  text-align: center;
  color: var(--van-text-color);
}

.ledger-temp-dialog-actions {
  display: flex;
  gap: 12px;
  margin-top: 16px;
}
.ledger-temp-dialog-actions .van-button {
  flex: 1;
}

.ledger-auto-hint {
  font-size: 12px;
  color: var(--van-text-color-2);
}

.ledger-sub-popup__head {
  padding: 12px 16px 8px;
  font-size: 15px;
  font-weight: 600;
  text-align: center;
  border-bottom: 1px solid var(--van-border-color);
}

.ledger-sub-popup__scroll {
  height: calc(62vh - 100px);
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
  padding-bottom: env(safe-area-inset-bottom);
}

.ledger-sub-popup :deep(.van-cell.is-disabled) {
  opacity: 0.45;
}
</style>
