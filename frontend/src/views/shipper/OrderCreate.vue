<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showFailToast, showLoadingToast, showSuccessToast, showToast, closeToast } from 'vant'

import { fetchAddresses, upsertContact } from '@/api/addresses'
import { createOrder } from '@/api/orders'
import { fetchProductsCatalog, type Product } from '@/api/products'
import { resolveStaticUrl } from '@/utils/assets'
import { normalizeHexColor } from '@/utils/productColor'
import { formatApiError } from '@/utils/apiError'
import { formatMoney2 } from '@/utils/formatMoney'
import { fetchUsers, type UserListItem } from '@/api/user'
import AmapPicker from '@/components/AmapPicker.vue'
import {
  clearOrderDraft,
  emptyDraft,
  loadOrderDraft,
  normalizeDraft,
  orderDraftHasMeaningfulContent,
  orderDraftIsResumable,
  recordOrderCreatedAnchor,
  saveOrderDraft,
  type OrderDraftV1,
} from '@/constants/orderDraft'

const route = useRoute()
const router = useRouter()
const isDispatcher = computed(() => route.path.startsWith('/dispatcher'))
const draftRole = computed(() => (isDispatcher.value ? 'dispatcher' : 'shipper'))

function productNameColorStyle(c: string | null | undefined) {
  const n = normalizeHexColor(c)
  return n ? { color: n } : undefined
}

const orderDateStr = computed(() => {
  const d = new Date()
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
})

const deliveryDescription = ref('')
const addressDetail = ref('')
const addressLng = ref<number | null>(null)
const addressLat = ref<number | null>(null)
const dongjiaPhone = ref('')
const bossPhone = ref('')
const remark = ref('')
const shipperId = ref<number | null>(null)
/** 派单员：临时货主称呼（不创建登录账号），与 shipperId 互斥 */
const tempShipperName = ref('')

const showMap = ref(false)
const shippers = ref<UserListItem[]>([])
const shipperPickerVisible = ref(false)
/** 弹层内选中系统货主 id；与临时称呼互斥 */
const shipperPickTempId = ref<number | null>(null)
/** 弹层内「临时货主」输入，确认后写入 tempShipperName */
const shipperPickerTempName = ref('')

const initialMapLngLat = computed(() => {
  if (addressLng.value != null && addressLat.value != null) {
    return { lng: addressLng.value, lat: addressLat.value }
  }
  return null
})

interface Line {
  product_name_snapshot: string
  quantity: number
  unit_price: number
  product_id: number | null
}

const lines = ref<Line[]>([{ product_name_snapshot: '', quantity: 1, unit_price: 0, product_id: null }])
const products = ref<Product[]>([])
const productPickerVisible = ref(false)
const productPickerIndex = ref(0)
/** 选品弹窗内图片加载失败时回退为「无图」占位 */
const productPickerImgFailed = ref<Record<number, true>>({})

function onProductPickerImgError(productId: number) {
  productPickerImgFailed.value = { ...productPickerImgFailed.value, [productId]: true }
}

const submitting = ref(false)

/** 初次挂载：填充默认地址等，不视为用户编辑 */
const hydrating = ref(true)
/** 用户是否主动改过表单（自动带出地址不算） */
const draftUserEdited = ref(false)
/** 提交已成功：禁止卸载前再次写入草稿（避免「提交后草稿复活」） */
const draftPersistLocked = ref(false)

const selectedShipperLabel = computed(() => {
  const id = shipperId.value
  if (id != null) {
    const u = shippers.value.find((x) => x.id === id)
    return u ? `${u.full_name || '货主'} · ${u.phone}` : ''
  }
  const tn = tempShipperName.value.trim()
  return tn ? `临时：${tn}` : ''
})

function buildDraft(): OrderDraftV1 {
  return normalizeDraft({
    v: 1,
    deliveryDescription: deliveryDescription.value,
    addressDetail: addressDetail.value,
    addressLng: addressLng.value,
    addressLat: addressLat.value,
    dongjiaPhone: dongjiaPhone.value,
    bossPhone: bossPhone.value,
    remark: remark.value,
    lines: lines.value.map((ln) => ({ ...ln })),
    shipperId: shipperId.value,
    tempShipperName: tempShipperName.value,
    userEdited: draftUserEdited.value,
    lastSavedAt: Date.now(),
  })
}

let saveTimer: ReturnType<typeof setTimeout> | null = null
function schedulePersistDraft() {
  if (draftPersistLocked.value || hydrating.value) return
  if (!draftUserEdited.value) return
  if (saveTimer) clearTimeout(saveTimer)
  saveTimer = setTimeout(() => {
    saveTimer = null
    if (draftPersistLocked.value) return
    const d = buildDraft()
    if (orderDraftHasMeaningfulContent(draftRole.value, d)) {
      saveOrderDraft(draftRole.value, d)
    } else {
      clearOrderDraft(draftRole.value)
    }
  }, 400)
}

watch(
  [
    deliveryDescription,
    addressDetail,
    addressLng,
    addressLat,
    dongjiaPhone,
    bossPhone,
    remark,
    shipperId,
    tempShipperName,
    lines,
  ],
  () => {
    if (!hydrating.value) draftUserEdited.value = true
    schedulePersistDraft()
  },
  { deep: true },
)

function applyDraft(d: OrderDraftV1) {
  const n = normalizeDraft(d)
  deliveryDescription.value = n.deliveryDescription
  addressDetail.value = n.addressDetail
  addressLng.value = n.addressLng
  addressLat.value = n.addressLat
  dongjiaPhone.value = n.dongjiaPhone
  bossPhone.value = n.bossPhone
  remark.value = n.remark
  lines.value = n.lines.length ? n.lines.map((x) => ({ ...x })) : emptyDraft().lines
  shipperId.value = n.shipperId
  tempShipperName.value = n.tempShipperName ?? ''
  draftUserEdited.value = Boolean(n.userEdited)
}

function resetFormToEmpty() {
  const e = emptyDraft()
  deliveryDescription.value = e.deliveryDescription
  addressDetail.value = e.addressDetail
  addressLng.value = e.addressLng
  addressLat.value = e.addressLat
  dongjiaPhone.value = e.dongjiaPhone
  bossPhone.value = e.bossPhone
  remark.value = e.remark
  lines.value = e.lines.map((x) => ({ ...x }))
  shipperId.value = e.shipperId
  tempShipperName.value = e.tempShipperName ?? ''
  draftUserEdited.value = false
}

function addLine() {
  if (lines.value.length >= 10) {
    showFailToast('最多 10 组商品')
    return
  }
  lines.value.push({ product_name_snapshot: '', quantity: 1, unit_price: 0, product_id: null })
}

function removeLine(i: number) {
  if (lines.value.length <= 1) return
  lines.value.splice(i, 1)
}

function openProductPicker(i: number) {
  if (!products.value.length) {
    showToast('暂无商品目录，请直接在「商品类型」中填写')
    return
  }
  productPickerImgFailed.value = {}
  productPickerIndex.value = i
  productPickerVisible.value = true
}

function onProductRowClick(pr: Product) {
  if (!pr.is_active) return
  draftUserEdited.value = true
  const i = productPickerIndex.value
  lines.value[i].product_id = pr.id
  lines.value[i].product_name_snapshot = pr.name
  lines.value[i].unit_price = Number(pr.default_unit_price)
  productPickerVisible.value = false
}

/** 派单员可改单价：保留两位小数、非负 */
function onDispatcherUnitPriceInput(i: number, e: Event) {
  draftUserEdited.value = true
  const raw = (e.target as HTMLInputElement).value
  if (raw === '' || raw === '.') {
    lines.value[i].unit_price = 0
    return
  }
  const n = parseFloat(raw)
  if (!Number.isFinite(n) || n < 0) return
  lines.value[i].unit_price = Math.round(n * 100) / 100
}

async function loadShippers() {
  if (!isDispatcher.value) return
  try {
    shippers.value = await fetchUsers({ role: 'shipper', limit: 500 }, true)
  } catch {
    /* ignore */
  }
}

watch(shipperPickerVisible, (open) => {
  if (open) {
    shipperPickTempId.value = shipperId.value
    shipperPickerTempName.value = shipperId.value != null ? '' : tempShipperName.value
  }
})

function onPickerTempNameInput() {
  if (shipperPickerTempName.value.trim()) shipperPickTempId.value = null
}

function onSelectRegisteredShipper(id: number | null) {
  shipperPickTempId.value = id
  shipperPickerTempName.value = ''
}

function confirmShipperPick() {
  draftUserEdited.value = true
  const tn = shipperPickerTempName.value.trim()
  if (tn) {
    shipperId.value = null
    tempShipperName.value = tn
  } else if (shipperPickTempId.value != null) {
    shipperId.value = shipperPickTempId.value
    tempShipperName.value = ''
  } else {
    shipperId.value = null
    tempShipperName.value = ''
  }
  shipperPickerVisible.value = false
}

onMounted(async () => {
  hydrating.value = true
  const wantResume = route.query.resume === '1' || route.query.resume === 'true'
  const loaded = loadOrderDraft(draftRole.value)

  if (wantResume && loaded && orderDraftIsResumable(draftRole.value)) {
    applyDraft(loaded)
  } else {
    clearOrderDraft(draftRole.value)
    resetFormToEmpty()
  }

  try {
    products.value = await fetchProductsCatalog()
    if (isDispatcher.value) {
      await loadShippers()
    } else if (!wantResume) {
      const addrs = await fetchAddresses()
      const def = addrs.find((a) => a.is_default) || addrs[0]
      if (def) {
        addressDetail.value = def.detail_address
        addressLng.value = def.address_lng != null ? Number(def.address_lng) : null
        addressLat.value = def.address_lat != null ? Number(def.address_lat) : null
        dongjiaPhone.value = def.phone
      }
    }
  } catch {
    /* ignore */
  }

  await nextTick()
  hydrating.value = false
})

function onMapConfirm(payload: { address: string; lng: number; lat: number }) {
  draftUserEdited.value = true
  addressDetail.value = payload.address
  addressLng.value = payload.lng
  addressLat.value = payload.lat
}

async function onBossBlur() {
  if (isDispatcher.value) return
  const p = bossPhone.value.trim()
  if (p.length < 5) return
  try {
    await upsertContact(p)
  } catch {
    /* ignore */
  }
}

onBeforeUnmount(() => {
  if (saveTimer) {
    clearTimeout(saveTimer)
    saveTimer = null
  }
  if (draftPersistLocked.value) return
  const d = buildDraft()
  if (draftUserEdited.value && orderDraftHasMeaningfulContent(draftRole.value, d)) {
    saveOrderDraft(draftRole.value, d)
  } else {
    clearOrderDraft(draftRole.value)
  }
})

async function submit() {
  /** 只提交已填写商品名的行，忽略多余空行，避免误传两行导致列表显示「等2种」 */
  const filled = lines.value.filter((ln) => ln.product_name_snapshot.trim())
  if (filled.length === 0) {
    showFailToast('请至少填写一种商品')
    return
  }
  /** 草稿/API 可能把 quantity、unit_price 存成字符串；Number.isFinite 对字符串为 false，会导致无法提交 */
  for (let i = 0; i < filled.length; i++) {
    const ln = filled[i]
    const qty = Math.max(1, Math.floor(Number(ln.quantity)))
    const upRaw = Number(ln.unit_price)
    const up = Number.isFinite(upRaw) ? Math.max(0, Math.round(upRaw * 100) / 100) : 0
    filled[i] = { ...ln, quantity: qty, unit_price: up }
  }
  for (const ln of filled) {
    if (ln.quantity < 1) {
      showFailToast('数量至少为 1')
      return
    }
    if (!Number.isFinite(ln.unit_price) || ln.unit_price < 0) {
      showFailToast('单价须为非负数')
      return
    }
  }
  if (!addressDetail.value.trim()) {
    showFailToast('请填写送达地址或地图选点')
    return
  }

  submitting.value = true
  showLoadingToast({ message: '提交中…', forbidClick: true })
  try {
    const created = await createOrder({
      order_date: orderDateStr.value,
      delivery_description: deliveryDescription.value,
      address_detail: addressDetail.value,
      address_lng: addressLng.value,
      address_lat: addressLat.value,
      contact_dongjia_phone: dongjiaPhone.value,
      contact_boss_phone: bossPhone.value,
      remark: remark.value,
      ...(isDispatcher.value && shipperId.value != null ? { shipper_id: shipperId.value } : {}),
      ...(isDispatcher.value &&
      shipperId.value == null &&
      tempShipperName.value.trim()
        ? { temp_shipper_name: tempShipperName.value.trim() }
        : {}),
      lines: filled.map((ln) => ({
        product_id: ln.product_id,
        product_name_snapshot: ln.product_name_snapshot.trim(),
        quantity: ln.quantity,
        unit_price: ln.unit_price,
        line_total: ln.unit_price * ln.quantity,
      })),
    })
    recordOrderCreatedAnchor(draftRole.value, created.created_at)
    if (saveTimer) {
      clearTimeout(saveTimer)
      saveTimer = null
    }
    draftPersistLocked.value = true
    clearOrderDraft(draftRole.value)
    closeToast()
    showSuccessToast('下单成功')
    router.replace(isDispatcher.value ? '/dispatcher/pending' : '/shipper/orders')
  } catch (e: unknown) {
    closeToast()
    showFailToast(formatApiError(e, '提交失败'))
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="order-create">
    <van-cell-group v-if="isDispatcher" inset title="代下单">
      <van-field
        readonly
        is-link
        label="归属货主"
        :model-value="selectedShipperLabel"
        placeholder="可选，不选则订单暂无归属货主"
        @click="shipperPickerVisible = true"
      />
    </van-cell-group>

    <van-cell-group inset title="订单日期" :class="{ mt: isDispatcher }">
      <van-field :model-value="orderDateStr" readonly label="日期" />
    </van-cell-group>

    <van-cell-group inset title="送货信息" class="mt">
      <van-field v-model="deliveryDescription" label="位置描述" type="textarea" rows="2" placeholder="如路口、地标" />
      <van-field v-model="addressDetail" label="送达地址" type="textarea" rows="2" placeholder="详细地址" />
      <div class="map-row">
        <van-button type="primary" size="small" icon="location-o" @click="showMap = true">地图选点</van-button>
      </div>
      <van-field v-model="dongjiaPhone" label="东家电话" type="tel" placeholder="手机号" />
      <van-field v-model="bossPhone" label="老板电话" type="tel" placeholder="可选，将保存到联系人库" @blur="onBossBlur" />
    </van-cell-group>

    <van-cell-group inset title="商品明细" class="mt">
      <div v-for="(ln, i) in lines" :key="i" class="line-block">
        <div class="line-head">
          <span>第 {{ i + 1 }} 组</span>
          <van-button v-if="lines.length > 1" size="mini" type="danger" plain @click="removeLine(i)">删除</van-button>
        </div>
        <van-field
          v-model="ln.product_name_snapshot"
          label="商品类型"
          placeholder="名称或从商品库选择"
        />
        <van-field label="选商品库" readonly is-link placeholder="点击选择" @click="openProductPicker(i)" />
        <van-field v-model.number="ln.quantity" label="数量" type="digit" />
        <van-field v-if="isDispatcher" label="单价" placeholder="可修改单价">
          <template #input>
            <input
              class="van-field__control"
              type="number"
              inputmode="decimal"
              step="0.01"
              min="0"
              :value="ln.unit_price"
              @input="onDispatcherUnitPriceInput(i, $event)"
            />
          </template>
        </van-field>
        <van-field v-else :model-value="formatMoney2(ln.unit_price)" label="单价" readonly />
      </div>
      <div class="add-line">
        <van-button block plain type="primary" :disabled="lines.length >= 10" @click="addLine">添加商品</van-button>
      </div>
    </van-cell-group>

    <van-cell-group inset title="备注" class="mt">
      <van-field v-model="remark" type="textarea" rows="3" placeholder="备注说明" />
    </van-cell-group>

    <div class="submit-wrap">
      <van-button type="primary" block round :loading="submitting" @click="submit">
        {{ isDispatcher ? '提交订单（代货主下单）' : '提交订单' }}
      </van-button>
    </div>

    <van-popup
      v-model:show="productPickerVisible"
      round
      position="center"
      teleport="body"
      class="product-picker-float-wrap"
      :close-on-click-overlay="true"
    >
      <div class="product-picker-float">
        <div class="product-picker-float__head">
          <span class="product-picker-float__title">选择商品</span>
          <button
            type="button"
            class="product-picker-float__close"
            aria-label="关闭"
            @click="productPickerVisible = false"
          >
            <van-icon name="cross" size="20" />
          </button>
        </div>
        <div v-if="products.length" class="product-picker-float__list">
          <div
            v-for="pr in products"
            :key="pr.id"
            class="product-picker-float__row"
            :class="{ 'product-picker-float__row--off': !pr.is_active }"
            role="button"
            @click="onProductRowClick(pr)"
          >
            <div class="product-picker-float__img">
              <img
                v-if="pr.image_url && !productPickerImgFailed[pr.id]"
                :key="`${pr.id}-${pr.image_url}`"
                :src="resolveStaticUrl(pr.image_url)"
                loading="lazy"
                alt=""
                @error="onProductPickerImgError(pr.id)"
              />
              <span v-else class="product-picker-float__ph">无图</span>
            </div>
            <div class="product-picker-float__meta">
              <div class="product-picker-float__name" :style="productNameColorStyle(pr.name_color)">
                {{ pr.name }}
              </div>
              <div class="product-picker-float__price">¥{{ formatMoney2(pr.default_unit_price) }}</div>
            </div>
            <van-tag v-if="!pr.is_active" type="danger" class="product-picker-float__tag">已下架</van-tag>
          </div>
        </div>
        <div v-else class="picker-empty">暂无商品</div>
      </div>
    </van-popup>

    <van-popup v-model:show="shipperPickerVisible" round position="bottom" class="shipper-pick-popup">
      <div class="shipper-pick-sheet">
        <div class="shipper-pick-sheet__bar">
          <button type="button" class="shipper-pick-sheet__link" @click="shipperPickerVisible = false">取消</button>
          <span class="shipper-pick-sheet__title">归属货主</span>
          <button type="button" class="shipper-pick-sheet__link" @click="confirmShipperPick">确认</button>
        </div>
        <div class="shipper-pick-sheet__field">
          <van-field
            v-model="shipperPickerTempName"
            label="临时货主"
            placeholder="填写后仅记名下单，不创建登录账号"
            @update:model-value="onPickerTempNameInput"
          />
        </div>
        <div class="shipper-pick-sheet__list">
          <div
            class="shipper-pick-sheet__row"
            :class="{
              'shipper-pick-sheet__row--on': shipperPickTempId === null && !shipperPickerTempName.trim(),
            }"
            role="button"
            @click="onSelectRegisteredShipper(null)"
          >
            <span class="shipper-pick-sheet__label">暂不选择（订单暂无归属货主）</span>
            <van-icon
              v-if="shipperPickTempId === null && !shipperPickerTempName.trim()"
              name="success"
              class="shipper-pick-sheet__check"
            />
          </div>
          <div
            v-for="u in shippers"
            :key="u.id"
            class="shipper-pick-sheet__row"
            :class="{
              'shipper-pick-sheet__row--on': shipperPickTempId === u.id && !shipperPickerTempName.trim(),
            }"
            role="button"
            @click="onSelectRegisteredShipper(u.id)"
          >
            <span class="shipper-pick-sheet__label">{{ u.full_name || '货主' }} · {{ u.phone }}</span>
            <van-icon
              v-if="shipperPickTempId === u.id && !shipperPickerTempName.trim()"
              name="success"
              class="shipper-pick-sheet__check"
            />
          </div>
          <div v-if="!shippers.length" class="picker-empty shipper-pick-sheet__empty-tip">
            暂无已注册货主；可仅用上方「临时货主」记名
          </div>
        </div>
      </div>
    </van-popup>

    <AmapPicker
      v-model:show="showMap"
      :initial-lng-lat="initialMapLngLat"
      panel-title="送货地址选点"
      @confirm="onMapConfirm"
    />
  </div>
</template>

<style scoped>
.order-create {
  padding-bottom: max(24px, env(safe-area-inset-bottom));
}
.mt {
  margin-top: 12px;
}
.map-row {
  padding: 8px 16px;
}
.line-block {
  padding: 8px 0;
  border-bottom: 1px solid var(--van-border-color);
}
.line-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 16px 8px;
  font-size: 13px;
  color: var(--van-text-color-2);
}
.add-line {
  padding: 12px 16px;
}
.submit-wrap {
  padding: 20px 16px;
}
.picker-empty {
  padding: 24px;
  text-align: center;
  color: var(--van-text-color-3);
}
.shipper-pick-sheet {
  display: flex;
  flex-direction: column;
  max-height: min(72vh, 560px);
}
.shipper-pick-sheet__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 8px;
  border-bottom: 1px solid var(--van-border-color);
  flex-shrink: 0;
}
.shipper-pick-sheet__title {
  font-weight: 600;
  font-size: 16px;
  color: var(--van-text-color);
}
.shipper-pick-sheet__link {
  border: none;
  background: none;
  color: var(--van-primary-color);
  font-size: 15px;
  padding: 8px 12px;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}
.shipper-pick-sheet__list {
  overflow-y: auto;
  flex: 1;
  min-height: 0;
  -webkit-overflow-scrolling: touch;
}
.shipper-pick-sheet__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-bottom: 1px solid var(--van-border-color);
  gap: 8px;
}
.shipper-pick-sheet__row--on {
  background: var(--van-active-color);
}
.shipper-pick-sheet__field {
  flex-shrink: 0;
  padding: 4px 0 8px;
  border-bottom: 1px solid var(--van-border-color);
}
.shipper-pick-sheet__label {
  flex: 1;
  min-width: 0;
  font-size: 15px;
  text-align: left;
}
.shipper-pick-sheet__check {
  flex-shrink: 0;
  color: var(--van-primary-color);
  font-size: 18px;
}
.shipper-pick-sheet__empty-tip {
  border-bottom: none;
}
/* 居中浮窗：选商品列表（图 + 名称 + 价格） */
:deep(.product-picker-float-wrap) {
  width: min(92vw, 400px);
  max-width: 400px;
  background: transparent;
  overflow: visible;
}
.product-picker-float {
  max-height: min(72vh, 560px);
  display: flex;
  flex-direction: column;
  background: var(--van-background-2, #fff);
  border-radius: 16px;
  box-shadow: 0 12px 40px rgba(15, 23, 42, 0.18);
  overflow: hidden;
}
.product-picker-float__head {
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  padding: 14px 44px 12px;
  flex-shrink: 0;
  border-bottom: 1px solid var(--van-border-color, #ebedf0);
}
.product-picker-float__title {
  font-weight: 600;
  font-size: 16px;
  color: var(--van-text-color);
}
.product-picker-float__close {
  position: absolute;
  right: 10px;
  top: 50%;
  transform: translateY(-50%);
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  padding: 0;
  border: none;
  background: transparent;
  color: var(--van-text-color-2);
  cursor: pointer;
  border-radius: 8px;
  -webkit-tap-highlight-color: transparent;
}
.product-picker-float__close:active {
  background: var(--van-active-color);
}
.product-picker-float__list {
  overflow-y: auto;
  padding: 8px 12px 14px;
  flex: 1;
  min-height: 0;
  -webkit-overflow-scrolling: touch;
}
.product-picker-float__row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 10px;
  margin-bottom: 8px;
  border-radius: 12px;
  background: var(--van-background, #f7f8fa);
  cursor: pointer;
  border: 1px solid transparent;
  transition: background 0.15s ease;
}
.product-picker-float__row:last-child {
  margin-bottom: 0;
}
.product-picker-float__row:active:not(.product-picker-float__row--off) {
  background: var(--van-active-color);
}
.product-picker-float__row--off {
  cursor: default;
  opacity: 0.88;
}
.product-picker-float__row--off .product-picker-float__img {
  filter: grayscale(1);
  opacity: 0.8;
}
.product-picker-float__img {
  width: 56px;
  height: 56px;
  border-radius: 10px;
  overflow: hidden;
  background: var(--van-gray-3, #e8e8e8);
  flex-shrink: 0;
}
.product-picker-float__img img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.product-picker-float__ph {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  font-size: 11px;
  color: var(--van-text-color-3);
}
.product-picker-float__meta {
  flex: 1;
  min-width: 0;
}
.product-picker-float__name {
  font-size: 16px;
  font-weight: 600;
  line-height: 1.35;
  letter-spacing: 0.01em;
}
.product-picker-float__price {
  font-size: 15px;
  font-weight: 700;
  color: var(--van-danger-color, #ee0a24);
  margin-top: 6px;
  letter-spacing: 0.02em;
}
.product-picker-float__tag {
  flex-shrink: 0;
}
</style>
