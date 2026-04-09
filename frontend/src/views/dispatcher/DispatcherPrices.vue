<script setup lang="ts">
import {
  showConfirmDialog,
  showFailToast,
  showImagePreview,
  showLoadingToast,
  showSuccessToast,
  closeToast,
} from 'vant'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { notifyPriceChange } from '@/api/notificationsExtra'
import {
  createPriceRule,
  deletePriceRule,
  fetchPriceRules,
  updatePriceRule,
  type PriceRule,
} from '@/api/priceRules'
import {
  createProduct,
  deleteProduct,
  fetchProductsAll,
  uploadProductImage,
  updateProduct,
  type Product,
} from '@/api/products'
import { fetchUsers, type UserListItem } from '@/api/user'
import { formatApiError } from '@/utils/apiError'
import { formatMoney2 } from '@/utils/formatMoney'
import { normalizeHexColor, parseProductNameColorInput } from '@/utils/productColor'
import { resolveStaticUrl } from '@/utils/assets'

const tab = ref(0)
const products = ref<Product[]>([])
const rules = ref<PriceRule[]>([])
const shippers = ref<UserListItem[]>([])
const loading = ref(false)
const togglingId = ref<number | null>(null)

const showEditor = ref(false)
const editing = ref<Product | null>(null)
const isNewProduct = ref(false)
const formName = ref('')
const formPrice = ref('')
const formNameColor = ref('')
const formActive = ref(true)
const pendingImageFile = ref<File | null>(null)
const imagePreview = ref('')

/** 名称颜色预设 #RRGGBB */
const NAME_COLOR_SWATCHES = ['#323233', '#EE0A24', '#1989FA', '#07C160', '#FF976A', '#7232DD'] as const

const ruleBatchIds = ref<number[]>([])

/** 上架在前，下架置底；同组内新在前 */
const sortedProducts = computed(() =>
  [...products.value].sort((a, b) => {
    if (a.is_active !== b.is_active) return a.is_active ? -1 : 1
    return b.id - a.id
  }),
)

const activeProducts = computed(() => products.value.filter((p) => p.is_active))

async function load() {
  loading.value = true
  try {
    try {
      products.value = await fetchProductsAll()
    } catch (e: unknown) {
      products.value = []
      showFailToast(formatApiError(e, '商品列表加载失败'))
    }
    try {
      rules.value = await fetchPriceRules()
      for (const r of rules.value) {
        const n = Number(r.special_unit_price)
        if (!Number.isNaN(n)) r.special_unit_price = formatMoney2(n)
      }
      hydrateNotifiedFromStorage()
    } catch (e: unknown) {
      rules.value = []
      showFailToast(formatApiError(e, '特殊价规则加载失败'))
    }
    try {
      shippers.value = await fetchUsers({ role: 'shipper', limit: 500 })
    } catch (e: unknown) {
      shippers.value = []
      showFailToast(formatApiError(e, '货主列表加载失败'))
    }
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void load()
})

function openCreateProduct() {
  isNewProduct.value = true
  editing.value = null
  formName.value = ''
  formPrice.value = ''
  formNameColor.value = ''
  formActive.value = true
  pendingImageFile.value = null
  imagePreview.value = ''
  showEditor.value = true
}

function openEditProduct(p: Product) {
  isNewProduct.value = false
  editing.value = { ...p }
  formName.value = p.name
  formPrice.value = formatMoney2(p.default_unit_price)
  formNameColor.value = normalizeHexColor(p.name_color) ?? ''
  formActive.value = p.is_active
  pendingImageFile.value = null
  imagePreview.value = p.image_url ? resolveStaticUrl(p.image_url) : ''
  showEditor.value = true
}

function onNativeColorInput(e: Event) {
  const v = (e.target as HTMLInputElement).value
  formNameColor.value = normalizeHexColor(v) ?? v
}

function onImagePick(
  file: { file?: File } | ReadonlyArray<{ file?: File }>,
) {
  const item = Array.isArray(file) ? file[0] : file
  const f = item?.file
  if (!f) return
  if (!f.type.startsWith('image/')) {
    showFailToast('请选择图片文件')
    return
  }
  pendingImageFile.value = f
  imagePreview.value = URL.createObjectURL(f)
}

function productNameStyle(nameColor: string | null | undefined) {
  const c = normalizeHexColor(nameColor)
  return c ? { color: c } : undefined
}

function previewProductImage(url: string) {
  const u = url.trim()
  if (!u) return
  showImagePreview({
    images: [u],
    startPosition: 0,
    closeable: true,
    maxZoom: 4,
    minZoom: 1 / 4,
  })
}

function previewEditorImage() {
  if (!imagePreview.value) return
  previewProductImage(imagePreview.value)
}

/** 切换商品上架状态（直接在卡片上操作） */
async function toggleActive(p: Product, newActive: boolean) {
  togglingId.value = p.id
  try {
    const updated = await updateProduct(p.id, {
      name: p.name,
      default_unit_price: p.default_unit_price,
      is_active: newActive,
      name_color: p.name_color ?? null,
    })
    // 乐观更新本地数据
    const idx = products.value.findIndex((x) => x.id === p.id)
    if (idx >= 0) {
      products.value[idx] = { ...products.value[idx], ...updated }
    }
    // 如果是下架，询问是否通知
    if (!newActive && p.is_active) {
      try {
        await showConfirmDialog({
          title: '通知货主',
          message: '是否向全部货主发送该商品已下架的通知？',
          confirmButtonText: '发送',
          cancelButtonText: '暂不',
        })
        await notifyDelistToAll(updated)
      } catch {
        /* cancel */
      }
    }
  } catch (e: unknown) {
    showFailToast(formatApiError(e, '状态更新失败'))
  } finally {
    togglingId.value = null
  }
}

function validateProductEditorForm(): {
  name: string
  price: number
  nameColor: string | null
} | null {
  const name = formName.value.trim()
  if (!name) {
    showFailToast('请填写商品名称')
    return null
  }
  const price = Number(formPrice.value)
  if (Number.isNaN(price) || price < 0) {
    showFailToast('请输入有效价格')
    return null
  }
  const colorParsed = parseProductNameColorInput(formNameColor.value)
  if (!colorParsed.ok) {
    showFailToast('名称颜色须为 #RRGGBB，例如 #323233')
    return null
  }
  return { name, price, nameColor: colorParsed.value }
}

/** 新建：创建 → 可选上传图 → 关弹窗刷新 → 成功提示 → 可选通知 */
async function saveNewProduct(name: string, price: number, nameColor: string | null) {
  let p = await createProduct({
    name,
    default_unit_price: price,
    name_color: nameColor,
  })
  if (pendingImageFile.value) {
    try {
      p = await uploadProductImage(p.id, pendingImageFile.value)
    } catch (imgErr: unknown) {
      closeToast()
      showEditor.value = false
      await load()
      showFailToast(
        formatApiError(imgErr, '商品已创建，但图片上传失败，可在编辑中重新选择图片'),
      )
      try {
        await showConfirmDialog({
          title: '通知货主',
          message: '是否向全部货主发送新商品及默认价说明？（消息中心）',
          confirmButtonText: '发送',
          cancelButtonText: '暂不',
        })
        await notifyAllShippersDefault(p)
      } catch {
        /* cancel */
      }
      return
    }
  }
  closeToast()
  showEditor.value = false
  await load()
  showSuccessToast('已创建商品')
  try {
    await showConfirmDialog({
      title: '通知货主',
      message: '是否向全部货主发送新商品及默认价说明？（消息中心）',
      confirmButtonText: '发送',
      cancelButtonText: '暂不',
    })
    await notifyAllShippersDefault(p)
  } catch {
    /* cancel */
  }
}

/**
 * 编辑：PATCH 名称/价/名称色（显式 name_color 含 null）→ 可选上传图 → 刷新后按价格变化决定是否通知
 */
async function saveEditedProduct(
  prev: Product,
  name: string,
  price: number,
  nameColor: string | null,
) {
  const oldPrice = prev.default_unit_price
  let p = await updateProduct(prev.id, {
    name,
    default_unit_price: price,
    is_active: prev.is_active, // 保持原有上架状态，由卡片开关控制
    name_color: nameColor,
  })
  if (pendingImageFile.value) {
    try {
      p = await uploadProductImage(prev.id, pendingImageFile.value)
    } catch (imgErr: unknown) {
      closeToast()
      showEditor.value = false
      await load()
      showFailToast(formatApiError(imgErr, '信息已保存，但图片上传失败，可稍后在编辑中重传'))
      return
    }
  }
  closeToast()
  showEditor.value = false
  await load()
  const priceChanged = String(oldPrice) !== String(p.default_unit_price)
  if (priceChanged) {
    await maybeNotifyDefault(p, oldPrice)
  }
}

async function submitProductForm() {
  const v = validateProductEditorForm()
  if (!v) return
  const { name, price, nameColor } = v
  showLoadingToast({ message: '保存中…', forbidClick: true, duration: 0 })
  try {
    if (isNewProduct.value) {
      await saveNewProduct(name, price, nameColor)
    } else if (editing.value) {
      await saveEditedProduct(editing.value, name, price, nameColor)
    } else {
      closeToast()
    }
  } catch (e: unknown) {
    closeToast()
    showFailToast(formatApiError(e, '保存失败'))
  }
}

async function maybeNotifyDefault(p: Product, oldPrice: string | number) {
  if (String(oldPrice) === String(p.default_unit_price)) return
  try {
    await showConfirmDialog({
      title: '价格已保存',
      message: '默认价已变更，是否通知全部货主？',
      confirmButtonText: '通知全部货主',
      cancelButtonText: '暂不',
    })
    await notifyAllShippersDefault(p, oldPrice)
  } catch {
    /* cancel */
  }
}

async function notifyAllShippersDefault(p: Product, oldPrice?: string | number | null) {
  if (!shippers.value.length) {
    showFailToast('无货主账号')
    return
  }
  showLoadingToast({ message: '发送中…', forbidClick: true, duration: 0 })
  try {
    await notifyPriceChange({
      shipper_ids: shippers.value.map((s) => s.id),
      product_id: p.id,
      product_name: p.name,
      price_type: 'default',
      new_price: p.default_unit_price,
      old_price: oldPrice ?? null,
      product_image_url: p.image_url ? resolveStaticUrl(p.image_url) : null,
    })
    closeToast()
    showSuccessToast('已通知全部货主')
  } catch {
    closeToast()
    showFailToast('通知发送失败')
  }
}

async function notifyDelistToAll(p: Product) {
  if (!shippers.value.length) {
    showFailToast('无货主账号')
    return
  }
  showLoadingToast({ message: '发送中…', forbidClick: true, duration: 0 })
  try {
    await notifyPriceChange({
      shipper_ids: shippers.value.map((s) => s.id),
      product_id: p.id,
      product_name: `${p.name}（已下架）`,
      price_type: 'default',
      new_price: p.default_unit_price,
      old_price: p.default_unit_price,
      product_image_url: p.image_url ? resolveStaticUrl(p.image_url) : null,
    })
    closeToast()
    showSuccessToast('已通知全部货主')
  } catch {
    closeToast()
    showFailToast('通知发送失败')
  }
}

async function confirmDeleteProduct(p: Product) {
  try {
    await showConfirmDialog({
      title: '删除商品',
      message:
        `确定永久删除「${p.name}」？删除后派单端与货主选品中都不再显示；历史订单仍保留行快照，仅解除与商品的关联。此操作不可恢复。`,
    })
    try {
      await showConfirmDialog({
        title: '通知货主',
        message: '是否向全部货主发送该商品已从目录删除的说明？',
        confirmButtonText: '发送',
        cancelButtonText: '暂不',
      })
      if (!shippers.value.length) {
        showFailToast('无货主账号')
      } else {
        showLoadingToast({ message: '发送中…', forbidClick: true, duration: 0 })
        try {
          await notifyPriceChange({
            shipper_ids: shippers.value.map((s) => s.id),
            product_id: p.id,
            product_name: `${p.name}（已删除）`,
            price_type: 'default',
            new_price: p.default_unit_price,
            old_price: p.default_unit_price,
            product_image_url: p.image_url ? resolveStaticUrl(p.image_url) : null,
          })
          closeToast()
        } catch {
          closeToast()
          showFailToast('通知发送失败')
        }
      }
    } catch {
      /* 不通知 */
    }
    showLoadingToast({ message: '删除中…', forbidClick: true, duration: 0 })
    try {
      await deleteProduct(p.id)
      closeToast()
      showEditor.value = false
      editing.value = null
      showSuccessToast('已删除')
      await load()
    } catch (e: unknown) {
      closeToast()
      showFailToast(formatApiError(e, '删除失败'))
    }
  } catch (e) {
    if (e !== 'cancel') showFailToast('操作失败')
  }
}

/** —— 货主特殊价 —— */
const showAddRule = ref(false)
const pickS = ref(false)
const pickP = ref(false)
const addShipperId = ref<number | null>(null)
const addProductId = ref<number | null>(null)
const addPrice = ref('')

const LS_PRICE_RULE_NOTIFIED = 'sorders_price_rule_notified_ids'

/** 已成功「保存并发送通知」的规则 id：列表只读 + 主按钮仅为「编辑」；持久化避免刷新后变回「保存并通知」 */
const ruleNotifiedOnce = ref<Record<number, boolean>>({})

function hydrateNotifiedFromStorage() {
  try {
    const raw = localStorage.getItem(LS_PRICE_RULE_NOTIFIED)
    if (!raw) return
    const stored: number[] = JSON.parse(raw)
    const ids = new Set(rules.value.map((r) => r.id))
    const next = { ...ruleNotifiedOnce.value }
    const valid: number[] = []
    for (const id of stored) {
      if (ids.has(id)) {
        next[id] = true
        valid.push(id)
      }
    }
    ruleNotifiedOnce.value = next
    if (valid.length !== stored.length) {
      localStorage.setItem(LS_PRICE_RULE_NOTIFIED, JSON.stringify(valid))
    }
  } catch {
    /* ignore */
  }
}

function persistNotifiedId(id: number) {
  ruleNotifiedOnce.value = { ...ruleNotifiedOnce.value, [id]: true }
  try {
    const raw = localStorage.getItem(LS_PRICE_RULE_NOTIFIED)
    const set = new Set<number>(raw ? (JSON.parse(raw) as number[]) : [])
    set.add(id)
    localStorage.setItem(LS_PRICE_RULE_NOTIFIED, JSON.stringify([...set]))
  } catch {
    /* ignore */
  }
}

function removeNotifiedIdFromStorage(id: number) {
  const next = { ...ruleNotifiedOnce.value }
  delete next[id]
  ruleNotifiedOnce.value = next
  try {
    const raw = localStorage.getItem(LS_PRICE_RULE_NOTIFIED)
    if (!raw) return
    const ids = (JSON.parse(raw) as number[]).filter((x) => x !== id)
    localStorage.setItem(LS_PRICE_RULE_NOTIFIED, JSON.stringify(ids))
  } catch {
    /* ignore */
  }
}

const showRuleEditor = ref(false)
const ruleEditRow = ref<PriceRule | null>(null)
const ruleEditPrice = ref('')

/** 未通知过的规则：每条单独一张卡，保存并通知后才并入货主合并卡 */
const pendingRules = computed(() =>
  rules.value.filter((r) => !ruleNotifiedOnce.value[r.id]),
)

type ShipperRuleGroup = {
  shipperId: number
  shipperName: string
  rules: PriceRule[]
}

/** 已通知过的规则：同一货主合并为一张卡片 */
const shipperRuleGroups = computed((): ShipperRuleGroup[] => {
  const notified = rules.value.filter((r) => ruleNotifiedOnce.value[r.id])
  const order: number[] = []
  const map = new Map<number, PriceRule[]>()
  for (const r of notified) {
    if (!map.has(r.shipper_id)) {
      order.push(r.shipper_id)
      map.set(r.shipper_id, [])
    }
    map.get(r.shipper_id)!.push(r)
  }
  return order.map((shipperId) => {
    const list = map.get(shipperId)!
    return {
      shipperId,
      shipperName: list[0]?.shipper_name ?? `#${shipperId}`,
      rules: list,
    }
  })
})

/** 点击货主名：下方浮层（Popover）选择货主 */
type ShipperPickMode =
  | { kind: 'single'; ruleId: number }
  | { kind: 'group'; ruleIds: number[] }
const shipperPickMode = ref<ShipperPickMode | null>(null)
/** 仅允许一个货主浮层打开：'p-{ruleId}' | 'g-{shipperId}' */
const shipperPopoverKey = ref<string | null>(null)

function openPickShipperForRule(r: PriceRule) {
  const key = `p-${r.id}`
  if (shipperPopoverKey.value === key) {
    shipperPopoverKey.value = null
    shipperPickMode.value = null
    return
  }
  shipperPickMode.value = { kind: 'single', ruleId: r.id }
  shipperPopoverKey.value = key
}

function openPickShipperForGroup(g: ShipperRuleGroup) {
  const key = `g-${g.shipperId}`
  if (shipperPopoverKey.value === key) {
    shipperPopoverKey.value = null
    shipperPickMode.value = null
    return
  }
  shipperPickMode.value = { kind: 'group', ruleIds: g.rules.map((x) => x.id) }
  shipperPopoverKey.value = key
}

function onShipperPopoverShowUpdate(show: boolean, key: string) {
  if (!show && shipperPopoverKey.value === key) {
    shipperPopoverKey.value = null
    shipperPickMode.value = null
  }
}

function closeRuleShipperPicker() {
  shipperPopoverKey.value = null
  shipperPickMode.value = null
}

async function onPickShipperInRulePicker(s: UserListItem) {
  const mode = shipperPickMode.value
  if (!mode) {
    closeRuleShipperPicker()
    return
  }
  if (mode.kind === 'single') {
    const r = rules.value.find((x) => x.id === mode.ruleId)
    if (!r || r.shipper_id === s.id) {
      closeRuleShipperPicker()
      return
    }
    showLoadingToast({ message: '更新中…', forbidClick: true, duration: 0 })
    try {
      const updated = await updatePriceRule(r.id, { shipper_id: s.id })
      updated.special_unit_price = formatMoney2(updated.special_unit_price)
      const idx = rules.value.findIndex((x) => x.id === r.id)
      if (idx >= 0) rules.value[idx] = updated
      closeToast()
      showSuccessToast('已更换货主')
    } catch (e: unknown) {
      closeToast()
      showFailToast(formatApiError(e, '更换货主失败'))
    }
    closeRuleShipperPicker()
    return
  }
  const targetId = s.id
  showLoadingToast({ message: '更新中…', forbidClick: true, duration: 0 })
  try {
    for (const rid of mode.ruleIds) {
      const row = rules.value.find((x) => x.id === rid)
      if (!row || row.shipper_id === targetId) continue
      const updated = await updatePriceRule(rid, { shipper_id: targetId })
      updated.special_unit_price = formatMoney2(updated.special_unit_price)
      const idx = rules.value.findIndex((x) => x.id === rid)
      if (idx >= 0) rules.value[idx] = updated
    }
    closeToast()
    showSuccessToast('已更换货主')
  } catch (e: unknown) {
    closeToast()
    showFailToast(formatApiError(e, '更换货主失败'))
    await load()
  }
  closeRuleShipperPicker()
}

function productForRule(r: PriceRule): Product | undefined {
  return products.value.find((x) => x.id === r.product_id)
}

function ruleProductDisplayName(r: PriceRule) {
  return productForRule(r)?.name ?? r.product_name ?? `#${r.product_id}`
}

function normalizeRulePriceInput(r: PriceRule) {
  const raw = r.special_unit_price
  const n = Number(typeof raw === 'string' ? String(raw).trim() : raw)
  if (Number.isNaN(n) || n < 0) return
  r.special_unit_price = formatMoney2(n)
}

const addRuleSelectedProduct = computed(() => {
  if (addProductId.value == null) return null
  return products.value.find((x) => x.id === addProductId.value) ?? null
})

function openAddRuleDialog() {
  addPrice.value = ''
  addShipperId.value = null
  addProductId.value = null
  showAddRule.value = true
}

function rulePrimaryLabel(r: PriceRule) {
  return ruleNotifiedOnce.value[r.id] ? '编辑' : '保存并通知'
}

function onRulePrimaryClick(r: PriceRule) {
  if (!ruleNotifiedOnce.value[r.id]) {
    void saveRule(r)
    return
  }
  openRuleEditor(r)
}

function openRuleEditor(r: PriceRule) {
  ruleEditRow.value = { ...r }
  ruleEditPrice.value = formatMoney2(r.special_unit_price)
  showRuleEditor.value = true
}

function closeRuleEditor() {
  showRuleEditor.value = false
}

function onRuleEditorClosed() {
  ruleEditRow.value = null
  ruleEditPrice.value = ''
}

async function confirmRuleEditor() {
  const r = ruleEditRow.value
  if (!r) return
  const pr = Number(ruleEditPrice.value)
  if (Number.isNaN(pr) || pr < 0) {
    showFailToast('请输入有效单价')
    return
  }
  const fresh = await fetchPriceRules()
  const old = fresh.find((x) => x.id === r.id)?.special_unit_price
  showLoadingToast({ message: '保存并通知中…', forbidClick: true, duration: 0 })
  try {
    const updated = await updatePriceRule(r.id, { special_unit_price: pr })
    const idx = rules.value.findIndex((x) => x.id === r.id)
    if (idx >= 0) {
      updated.special_unit_price = formatMoney2(updated.special_unit_price)
      rules.value[idx] = updated
    }
    const prod = products.value.find((x) => x.id === r.product_id)
    await notifyPriceChange({
      shipper_ids: [r.shipper_id],
      product_id: r.product_id,
      product_name: updated.product_name || r.product_name || prod?.name || '商品',
      price_type: 'special',
      new_price: updated.special_unit_price,
      old_price: old ?? null,
      product_image_url: prod?.image_url ? resolveStaticUrl(prod.image_url) : null,
    })
    closeToast()
    showSuccessToast('已保存并已通知该货主')
    persistNotifiedId(r.id)
    showRuleEditor.value = false
  } catch (e: unknown) {
    closeToast()
    showFailToast(formatApiError(e, '保存或通知失败'))
  }
}

async function saveRule(r: PriceRule) {
  const fresh = await fetchPriceRules()
  const old = fresh.find((x) => x.id === r.id)?.special_unit_price
  try {
    const updated = await updatePriceRule(r.id, { special_unit_price: r.special_unit_price })
    const idx = rules.value.findIndex((x) => x.id === r.id)
    if (idx >= 0) {
      updated.special_unit_price = formatMoney2(updated.special_unit_price)
      rules.value[idx] = updated
    }
    const prod = products.value.find((x) => x.id === r.product_id)
    try {
      await showConfirmDialog({
        title: '已保存',
        message: '是否仅通知该货主？',
        confirmButtonText: '发送通知',
        cancelButtonText: '暂不',
      })
    } catch {
      return
    }
    try {
      await notifyPriceChange({
        shipper_ids: [r.shipper_id],
        product_id: r.product_id,
        product_name: updated.product_name || r.product_name || prod?.name || '商品',
        price_type: 'special',
        new_price: updated.special_unit_price,
        old_price: old ?? null,
        product_image_url: prod?.image_url ? resolveStaticUrl(prod.image_url) : null,
      })
      showSuccessToast('已发送')
      persistNotifiedId(r.id)
    } catch {
      showFailToast('通知发送失败')
    }
  } catch (e: unknown) {
    showFailToast(formatApiError(e, '保存失败'))
  }
}

type BatchEditDraftRow = {
  ruleId: number
  productId: number
  shipperTitle: string
  productName: string
  /** 商品目录名称色，用于输入框内展示 */
  nameColor: string | null
  specialUnitPrice: string
}

const showBatchEdit = ref(false)
const batchEditRows = ref<BatchEditDraftRow[]>([])
/** 勾选规则进行批量操作；为 true 时显示勾选框与「编辑」 */
const batchSelectMode = ref(false)

/** CheckboxGroup 可能把 name 同步成 string，与 number 的 rule.id 用 includes 会匹配失败 */
function rulesFromBatchSelection(): PriceRule[] {
  const ids = new Set(ruleBatchIds.value.map((id) => Number(id)))
  return rules.value.filter((r) => ids.has(r.id))
}

function resetSpecialPriceBatchUi() {
  showBatchEdit.value = false
  batchEditRows.value = []
  batchSelectMode.value = false
  ruleBatchIds.value = []
  shipperPopoverKey.value = null
  shipperPickMode.value = null
}

watch(tab, (t) => {
  if (t !== 1) {
    resetSpecialPriceBatchUi()
  }
})

onBeforeUnmount(() => {
  resetSpecialPriceBatchUi()
})

function toggleBatchSelectMode() {
  const next = !batchSelectMode.value
  batchSelectMode.value = next
  if (next) {
    ruleBatchIds.value = rules.value.map((r) => r.id)
  } else {
    ruleBatchIds.value = []
  }
}

function openBatchEditForSelected() {
  const sel = rulesFromBatchSelection()
  if (!sel.length) {
    showFailToast('请先勾选要编辑的规则')
    return
  }
  openBatchEditDialog(sel)
}

function batchEditNameCssVars(row: BatchEditDraftRow) {
  const c = normalizeHexColor(row.nameColor)
  return { '--batch-name-fg': c ?? '#000' } as Record<string, string>
}

function openBatchEditDialog(sel: PriceRule[]) {
  if (!sel.length) {
    showFailToast('没有可编辑的规则')
    return
  }
  batchEditRows.value = sel.map((r) => {
    const p = productForRule(r)
    return {
      ruleId: r.id,
      productId: r.product_id,
      shipperTitle: r.shipper_name ?? `#${r.shipper_id}`,
      productName: p?.name ?? r.product_name ?? `#${r.product_id}`,
      nameColor: p?.name_color ?? null,
      specialUnitPrice: formatMoney2(r.special_unit_price),
    }
  })
  showBatchEdit.value = true
}

/** 弹窗关闭（取消、点遮罩、destroy-on-close）：退出批量选择并清空勾选 */
function onBatchEditPopupClosed() {
  batchEditRows.value = []
  ruleBatchIds.value = []
  batchSelectMode.value = false
}

function closeBatchEditDialog() {
  showBatchEdit.value = false
  batchEditRows.value = []
}

async function submitBatchEdit() {
  if (!batchEditRows.value.length) {
    closeBatchEditDialog()
    return
  }
  showLoadingToast({ message: '保存中…', forbidClick: true, duration: 0 })
  try {
    for (const row of batchEditRows.value) {
      const r = rules.value.find((x) => x.id === row.ruleId)
      if (!r) continue
      const p = products.value.find((x) => x.id === row.productId)
      const nameTrim = row.productName.trim()
      if (!nameTrim) {
        closeToast()
        showFailToast('商品名称不能为空')
        return
      }
      const pr = Number(row.specialUnitPrice)
      if (Number.isNaN(pr) || pr < 0) {
        closeToast()
        showFailToast('请输入有效特殊单价')
        return
      }
      if (p && nameTrim !== p.name) {
        const updatedP = await updateProduct(p.id, {
          name: nameTrim,
          default_unit_price: p.default_unit_price,
          is_active: p.is_active,
          name_color: p.name_color ?? null,
        })
        const pi = products.value.findIndex((x) => x.id === p.id)
        if (pi >= 0) products.value[pi] = { ...products.value[pi], ...updatedP }
      }
      const nextPrice = formatMoney2(pr)
      const cur = formatMoney2(r.special_unit_price)
      if (nextPrice !== cur) {
        const updated = await updatePriceRule(r.id, { special_unit_price: pr })
        updated.special_unit_price = formatMoney2(updated.special_unit_price)
        const idx = rules.value.findIndex((x) => x.id === r.id)
        if (idx >= 0) rules.value[idx] = updated
      }
    }
    closeToast()
    showSuccessToast('已保存')
    closeBatchEditDialog()
    await load()
  } catch (e: unknown) {
    closeToast()
    showFailToast(formatApiError(e, '保存失败'))
  }
}

async function submitAddRule() {
  if (!addShipperId.value || !addProductId.value) {
    showFailToast('请选择货主与商品')
    return
  }
  const pr = Number(addPrice.value)
  if (Number.isNaN(pr) || pr < 0) {
    showFailToast('请输入有效单价')
    return
  }
  try {
    await createPriceRule({
      shipper_id: addShipperId.value,
      product_id: addProductId.value,
      special_unit_price: pr,
    })
    showSuccessToast('已添加')
    showAddRule.value = false
    addPrice.value = ''
    addShipperId.value = null
    addProductId.value = null
    await load()
  } catch (e: unknown) {
    showFailToast(formatApiError(e, '添加失败'))
  }
}

async function removeRule(r: PriceRule) {
  try {
    await showConfirmDialog({ title: '删除特殊价', message: '确定删除该条特殊定价？' })
    if (ruleEditRow.value?.id === r.id) showRuleEditor.value = false
    await deletePriceRule(r.id)
    removeNotifiedIdFromStorage(r.id)
    showSuccessToast('已删除')
    await load()
  } catch (e) {
    if (e !== 'cancel') showFailToast('删除失败')
  }
}
</script>

<template>
  <div class="prices role-tool-page">
    <van-tabs v-model:active="tab">
      <van-tab title="商品默认价">
        <div class="tab-hint">
          关闭上方「上架」开关并保存即下架（仍保留在列表末尾、变灰，非删除）。「删除商品」才从目录移除。名称可选颜色；价格保留两位小数。下架/删除后均可选择是否通知全部货主。
        </div>
        <van-loading v-if="loading" vertical class="ld">加载中</van-loading>
        <template v-else>
          <van-empty v-if="!sortedProducts.length" description="暂无商品" />
          <div v-else class="p-grid">
            <div
              v-for="p in sortedProducts"
              :key="p.id"
              class="p-card"
              :class="{ 'p-card--off': !p.is_active }"
            >
              <!-- 商品图片区域 -->
              <div class="p-card__img-wrap">
                <img
                  v-if="p.image_url"
                  :key="`${p.id}-${p.image_url}`"
                  :src="resolveStaticUrl(p.image_url)"
                  loading="lazy"
                  alt=""
                  class="p-card__img"
                  title="点击查看大图，可双指缩放"
                  @click.stop="previewProductImage(resolveStaticUrl(p.image_url))"
                  @error="($event.target as HTMLImageElement).style.display = 'none'"
                />
                <div v-else class="p-card__placeholder">无图</div>
                <!-- 已下架红色标签 - 右上角醒目显示 -->
                <span v-if="!p.is_active" class="p-card__offline-badge">已下架</span>
              </div>
              <!-- 商品信息区域 - 点击打开编辑 -->
              <div class="p-card__body" role="button" @click="openEditProduct(p)">
                <div class="p-card__name" :style="productNameStyle(p.name_color)">
                  {{ p.name }}
                </div>
                <div class="p-card__price">¥{{ formatMoney2(p.default_unit_price) }}</div>
              </div>
              <!-- 上架开关 - 卡片底部独立操作区 -->
              <div class="p-card__toggle" @click.stop>
                <span class="p-card__toggle-label">{{ p.is_active ? '上架中' : '已下架' }}</span>
                <van-switch
                  :model-value="p.is_active"
                  size="18"
                  :loading="togglingId === p.id"
                  @update:model-value="(v: boolean) => toggleActive(p, v)"
                />
              </div>
            </div>
          </div>
        </template>

      </van-tab>

      <van-tab title="货主特殊价">
        <div class="tab-hint">
          新增后每条先单独成卡；点「保存并通知」成功后并入该货主合并卡。点「批量选择」会全选规则并出现「编辑」；可再改勾选；保存或退出选择会清空勾选。卡顶货主名可换货主。
        </div>
        <div class="rule-actions">
          <van-button type="primary" size="small" plain @click="openAddRuleDialog">新增特殊价</van-button>
          <van-button
            type="warning"
            size="small"
            plain
            :disabled="!rules.length"
            @click="toggleBatchSelectMode"
          >
            {{ batchSelectMode ? '退出选择' : '批量选择' }}
          </van-button>
          <van-button
            v-show="batchSelectMode"
            type="primary"
            size="small"
            :disabled="!ruleBatchIds.length"
            @click="openBatchEditForSelected"
          >
            编辑
          </van-button>
        </div>
        <van-loading v-if="loading" vertical class="ld">加载中</van-loading>
        <van-empty v-else-if="!rules.length" description="暂无特殊定价" />
        <van-checkbox-group v-model="ruleBatchIds">
          <!-- 未通知：每条规则单独一张卡 -->
          <div v-for="r in pendingRules" :key="'p-' + r.id" class="rule-block rule-card">
            <div class="rule-card__shipper-wrap">
              <van-popover
                trigger="manual"
                :show="shipperPopoverKey === 'p-' + r.id"
                placement="bottom-start"
                :offset="[0, 8]"
                :show-arrow="true"
                theme="light"
                teleport="body"
                overlay
                close-on-click-overlay
                :overlay-style="{ background: 'rgba(0, 0, 0, 0.25)' }"
                class="rule-shipper-popover"
                @update:show="(v: boolean) => onShipperPopoverShowUpdate(v, 'p-' + r.id)"
              >
                <template #reference>
                  <button
                    type="button"
                    class="rule-card__shipper-chip"
                    @click.stop="openPickShipperForRule(r)"
                  >
                    <span class="rule-card__shipper-text">{{
                      r.shipper_name || `#${r.shipper_id}`
                    }}</span>
                    <van-icon name="arrow-down" class="rule-card__shipper-caret" />
                  </button>
                </template>
                <div class="rule-shipper-float">
                  <div class="rule-shipper-float__head">选择货主</div>
                  <div class="rule-shipper-float__scroll">
                    <van-cell
                      v-for="s in shippers"
                      :key="'spf-' + r.id + '-' + s.id"
                      :title="s.full_name || s.phone"
                      clickable
                      @click="onPickShipperInRulePicker(s)"
                    />
                  </div>
                </div>
              </van-popover>
            </div>
            <div class="rule-card__line">
              <div class="rule-card__body">
                <van-checkbox
                  v-show="batchSelectMode"
                  :name="r.id"
                  class="rule-card__chk"
                  @click.stop
                />
                <div class="rule-card__merge">
                  <div
                    class="rule-card__product-line"
                    :style="productNameStyle(productForRule(r)?.name_color)"
                  >
                    {{ ruleProductDisplayName(r) }}
                  </div>
                  <div class="rule-card__price-row">
                    <span class="rule-card__price-label">特殊单价</span>
                    <van-field
                      v-model="r.special_unit_price"
                      type="number"
                      :border="false"
                      class="rule-card__field"
                      input-align="right"
                      @blur="normalizeRulePriceInput(r)"
                    />
                  </div>
                </div>
              </div>
              <div class="rule-btns">
                <van-button size="small" type="primary" @click="onRulePrimaryClick(r)">
                  {{ rulePrimaryLabel(r) }}
                </van-button>
                <van-button size="small" plain type="danger" @click="removeRule(r)">删除</van-button>
              </div>
            </div>
          </div>
          <!-- 已通知：按货主合并 -->
          <div v-for="g in shipperRuleGroups" :key="'g-' + g.shipperId" class="rule-block rule-card">
            <div class="rule-card__shipper-wrap">
              <van-popover
                trigger="manual"
                :show="shipperPopoverKey === 'g-' + g.shipperId"
                placement="bottom-start"
                :offset="[0, 8]"
                :show-arrow="true"
                theme="light"
                teleport="body"
                overlay
                close-on-click-overlay
                :overlay-style="{ background: 'rgba(0, 0, 0, 0.25)' }"
                class="rule-shipper-popover"
                @update:show="(v: boolean) => onShipperPopoverShowUpdate(v, 'g-' + g.shipperId)"
              >
                <template #reference>
                  <button
                    type="button"
                    class="rule-card__shipper-chip"
                    @click.stop="openPickShipperForGroup(g)"
                  >
                    <span class="rule-card__shipper-text">{{ g.shipperName }}</span>
                    <van-icon name="arrow-down" class="rule-card__shipper-caret" />
                  </button>
                </template>
                <div class="rule-shipper-float">
                  <div class="rule-shipper-float__head">选择货主</div>
                  <div class="rule-shipper-float__scroll">
                    <van-cell
                      v-for="s in shippers"
                      :key="'sgf-' + g.shipperId + '-' + s.id"
                      :title="s.full_name || s.phone"
                      clickable
                      @click="onPickShipperInRulePicker(s)"
                    />
                  </div>
                </div>
              </van-popover>
            </div>
            <div v-for="r in g.rules" :key="r.id" class="rule-card__line">
              <div class="rule-card__body">
                <van-checkbox
                  v-show="batchSelectMode"
                  :name="r.id"
                  class="rule-card__chk"
                  @click.stop
                />
                <div class="rule-card__merge">
                  <div
                    class="rule-card__product-line"
                    :style="productNameStyle(productForRule(r)?.name_color)"
                  >
                    {{ ruleProductDisplayName(r) }}
                  </div>
                  <div class="rule-card__price-row">
                    <span class="rule-card__price-label">特殊单价</span>
                    <span class="rule-card__price-value">{{ formatMoney2(r.special_unit_price) }}</span>
                  </div>
                </div>
              </div>
              <div class="rule-btns">
                <van-button size="small" type="primary" @click="onRulePrimaryClick(r)">
                  {{ rulePrimaryLabel(r) }}
                </van-button>
                <van-button size="small" plain type="danger" @click="removeRule(r)">删除</van-button>
              </div>
            </div>
          </div>
        </van-checkbox-group>
      </van-tab>
    </van-tabs>

    <!-- 仅「商品默认价」页显示；自定义圆形按钮，替代 FloatingBubble（无磁吸小球） -->
    <div
      v-show="tab === 0"
      class="prices-fab"
      role="button"
      aria-label="新建商品"
      @click="openCreateProduct"
    >
      <van-icon name="plus" :size="28" />
    </div>

    <!-- 商品新建/编辑：居中窄弹窗 -->
    <van-popup
      v-model:show="showEditor"
      position="center"
      round
      teleport="body"
      class="product-editor-popup"
    >
      <div class="product-editor-dialog">
        <div class="product-editor-dialog__title">
          {{ isNewProduct ? '新建商品' : '编辑商品' }}
        </div>
        <van-cell-group inset>
          <van-field v-model="formName" label="名称" placeholder="商品名称" />
          <van-cell title="名称颜色" class="cell-color">
            <template #value>
              <div class="color-swatches">
                <button
                  type="button"
                  class="color-swatches__clear"
                  :class="{ 'is-on': !formNameColor }"
                  title="默认色"
                  @click="formNameColor = ''"
                >
                  默认
                </button>
                <button
                  v-for="c in NAME_COLOR_SWATCHES"
                  :key="c"
                  type="button"
                  class="color-dot"
                  :class="{ 'is-on': formNameColor === c }"
                  :style="{ background: c }"
                  :title="c"
                  @click="formNameColor = c"
                />
                <label class="color-native-wrap" title="自选颜色">
                  <input
                    type="color"
                    class="color-native"
                    :value="formNameColor || '#323233'"
                    @input="onNativeColorInput"
                  />
                </label>
              </div>
            </template>
          </van-cell>
          <van-field v-model="formNameColor" label="色值" placeholder="#323233" maxlength="7" />
          <van-field v-model="formPrice" type="number" label="默认单价" placeholder="0.00" />
          <van-cell title="商品图片">
            <template #value>
              <van-uploader :max-count="1" :after-read="onImagePick">
                <div class="up-preview">
                  <img
                    v-if="imagePreview"
                    :src="imagePreview"
                    alt=""
                    title="点击查看大图，可双指缩放"
                    @click.stop="previewEditorImage"
                  />
                  <span v-else class="up-placeholder">点击上传</span>
                </div>
              </van-uploader>
            </template>
          </van-cell>
        </van-cell-group>
        <div class="product-editor-dialog__actions">
          <van-button block type="primary" size="small" @click="submitProductForm">确定</van-button>
          <van-button
            v-if="!isNewProduct && editing"
            block
            plain
            type="danger"
            size="small"
            @click="confirmDeleteProduct(editing)"
          >
            删除商品
          </van-button>
          <van-button block plain size="small" @click="showEditor = false">取消</van-button>
        </div>
      </div>
    </van-popup>

    <van-popup
      v-model:show="showAddRule"
      position="center"
      round
      teleport="body"
      class="add-rule-popup"
      :close-on-click-overlay="true"
    >
      <div class="add-rule-dialog">
        <div class="add-rule-dialog__title">新增特殊价</div>
        <van-cell-group inset>
          <van-field
            label="货主"
            readonly
            is-link
            placeholder="选择"
            :model-value="addShipperId ? shippers.find((x) => x.id === addShipperId)?.full_name || `#${addShipperId}` : ''"
            @click="pickS = true"
          />
          <van-field label="商品" readonly is-link @click="pickP = true">
            <template #input>
              <span
                v-if="addRuleSelectedProduct"
                class="add-rule-product-name"
                :style="productNameStyle(addRuleSelectedProduct.name_color)"
              >
                {{ addRuleSelectedProduct.name }}
              </span>
              <span v-else class="add-rule-product-placeholder">选择</span>
            </template>
          </van-field>
          <van-field v-model="addPrice" type="number" label="特殊单价" placeholder="0.00" />
        </van-cell-group>
        <div class="add-rule-dialog__actions">
          <van-button block type="primary" size="small" @click="submitAddRule">提交</van-button>
          <van-button block plain size="small" @click="showAddRule = false">取消</van-button>
        </div>
      </div>
    </van-popup>

    <van-popup
      v-model:show="showBatchEdit"
      position="center"
      round
      teleport="body"
      class="batch-edit-popup"
      :close-on-click-overlay="true"
      destroy-on-close
      @closed="onBatchEditPopupClosed"
    >
      <div class="batch-edit-dialog">
        <div class="batch-edit-dialog__title">批量编辑</div>
        <p class="batch-edit-dialog__hint">共 {{ batchEditRows.length }} 条；修改商品名将同步到商品目录。</p>
        <div class="batch-edit-dialog__scroll">
          <div
            v-for="(row, idx) in batchEditRows"
            :key="row.ruleId"
            class="batch-edit-row"
          >
            <div class="batch-edit-row__meta">货主 · {{ row.shipperTitle }}</div>
            <van-field
              v-model="row.productName"
              label="商品名称"
              placeholder="名称"
              class="batch-edit-name-wrap"
              :style="batchEditNameCssVars(row)"
            />
            <van-field
              v-model="row.specialUnitPrice"
              type="number"
              label="特殊单价"
              placeholder="0.00"
              class="batch-edit-price-wrap"
            />
            <div v-if="idx < batchEditRows.length - 1" class="batch-edit-row__sep" />
          </div>
        </div>
        <div class="batch-edit-dialog__actions">
          <van-button block type="primary" size="small" @click="submitBatchEdit">保存</van-button>
          <van-button block plain size="small" @click="closeBatchEditDialog">取消</van-button>
        </div>
      </div>
    </van-popup>

    <!-- 已通知过的特殊价：列表上点「编辑」进入，确定后保存并自动通知 -->
    <van-popup
      v-model:show="showRuleEditor"
      position="center"
      round
      teleport="body"
      class="add-rule-popup"
      :close-on-click-overlay="true"
      @closed="onRuleEditorClosed"
    >
      <div v-if="ruleEditRow" class="add-rule-dialog">
        <div class="add-rule-dialog__title">编辑特殊价</div>
        <p class="rule-edit-hint">
          <span class="rule-edit-hint__shipper">{{
            ruleEditRow.shipper_name || `#${ruleEditRow.shipper_id}`
          }}</span>
          <span> · </span>
          <span
            class="rule-edit-hint__product"
            :style="productNameStyle(productForRule(ruleEditRow)?.name_color)"
          >{{ ruleProductDisplayName(ruleEditRow) }}</span>
        </p>
        <van-cell-group inset>
          <van-field v-model="ruleEditPrice" type="number" label="特殊单价" placeholder="0.00" />
        </van-cell-group>
        <div class="add-rule-dialog__actions">
          <van-button block type="primary" size="small" @click="confirmRuleEditor">确定</van-button>
          <van-button block plain size="small" @click="closeRuleEditor">取消</van-button>
        </div>
      </div>
    </van-popup>

    <van-popup v-model:show="pickS" position="bottom" round>
      <van-nav-bar title="货主" left-text="关闭" @click-left="pickS = false" />
      <van-cell
        v-for="s in shippers"
        :key="s.id"
        :title="s.full_name || s.phone"
        @click=";(addShipperId = s.id), (pickS = false)"
      />
    </van-popup>
    <van-popup v-model:show="pickP" position="bottom" round>
      <van-nav-bar title="商品" left-text="关闭" @click-left="pickP = false" />
      <div class="pick-p-list">
        <van-cell
          v-for="p in activeProducts"
          :key="p.id"
          clickable
          @click=";(addProductId = p.id), (pickP = false)"
        >
          <template #title>
            <span class="pick-p-name" :style="productNameStyle(p.name_color)">{{ p.name }}</span>
          </template>
          <template #value>
            <span class="pick-p-default-price">¥{{ formatMoney2(p.default_unit_price) }}</span>
          </template>
        </van-cell>
      </div>
    </van-popup>

  </div>
</template>

<style scoped>
.prices {
  padding-bottom: 72px;
}
.tab-hint {
  font-size: 12px;
  color: var(--van-text-color-2);
  padding: 10px 16px 6px;
  line-height: 1.45;
}
.ld {
  padding: 24px;
}
.p-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  padding: 8px 10px 14px;
  align-items: start;
}
.p-card {
  background: var(--van-background-2, #fff);
  border: 1px solid var(--van-border-color);
  border-radius: 10px;
  overflow: hidden;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06);
  display: flex;
  flex-direction: column;
}
/* 整卡灰度处理（覆盖所有子元素） */
.p-card--off {
  filter: grayscale(100%);
  opacity: 0.75;
}
/* 固定竖向长方形画框（宽:高 ≈ 3:4），图片只缩放填入框内，框尺寸不随原图变化 */
.p-card__img-wrap {
  position: relative;
  width: 100%;
  aspect-ratio: 3 / 4;
  overflow: hidden;
  background: var(--van-gray-2, #f2f3f5);
}
.p-card__img {
  position: absolute;
  inset: 0;
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: center;
  cursor: zoom-in;
}
/* 图片加载失败时隐藏 */
.p-card__img[style*="display: none"] {
  display: none !important;
}
.p-card__placeholder {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 8px;
  font-size: 11px;
  color: var(--van-text-color-3);
}
/* 已下架红色标签 - 右上角醒目显示 */
.p-card__offline-badge {
  position: absolute;
  top: 0;
  right: 0;
  background: #ee0a24;
  color: #fff;
  font-size: 11px;
  font-weight: 600;
  padding: 2px 6px;
  border-bottom-left-radius: 6px;
  line-height: 1.4;
  letter-spacing: 0.02em;
  z-index: 1;
}
/* 商品信息区域 */
.p-card__body {
  flex: 1;
  cursor: pointer;
}
/* 商品名称 */
.p-card__name {
  padding: 6px 8px 0;
  font-size: 14px;
  font-weight: 700;
  line-height: 1.3;
  letter-spacing: 0.02em;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
/* 商品价格 */
.p-card__price {
  padding: 4px 8px 6px;
  font-size: 16px;
  font-weight: 700;
  color: var(--van-danger-color, #ee0a24);
  letter-spacing: 0.03em;
}
/* 上架开关区域 */
.p-card__toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 8px 8px;
  border-top: 1px solid var(--van-border-color);
  background: var(--van-background, #fff);
}
.p-card__toggle-label {
  font-size: 12px;
  color: var(--van-text-color-2);
}
.cell-color :deep(.van-cell__value) {
  flex: 1.2;
}
.color-swatches {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
}
.color-swatches__clear {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 6px;
  border: 1px solid var(--van-gray-5, #c8c9cc);
  background: var(--van-background-2, #fff);
  color: var(--van-text-color, #323233);
}
.color-swatches__clear.is-on {
  border-color: var(--van-primary-color, #1989fa);
  color: var(--van-primary-color, #1989fa);
}
.color-dot {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  border: 2px solid #fff;
  box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.12);
  padding: 0;
  cursor: pointer;
}
.color-dot.is-on {
  box-shadow: 0 0 0 2px var(--van-primary-color, #1989fa);
}
.color-native-wrap {
  display: inline-flex;
  align-items: center;
  cursor: pointer;
}
.color-native {
  width: 28px;
  height: 28px;
  padding: 0;
  border: none;
  background: transparent;
  cursor: pointer;
}
.rule-actions {
  display: flex;
  gap: 8px;
  padding: 8px 12px;
  flex-wrap: wrap;
}
.rule-block {
  margin-bottom: 10px;
}
/* 货主名为圆角略深块；选货主为贴名下方 Popover；商品名用目录 name_color，无则黑字；单价黑字 */
.rule-card {
  background: var(--van-background-2, #fff);
  border-radius: var(--van-radius-lg, 8px);
  overflow: hidden;
  margin-left: 16px;
  margin-right: 16px;
  border: 1px solid var(--van-border-color);
}
.rule-card__shipper-wrap {
  padding: 10px 12px 8px;
  border-bottom: 1px solid var(--van-border-color);
}
.rule-card__shipper-chip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
  box-sizing: border-box;
  margin: 0;
  padding: 10px 12px;
  font-size: 15px;
  font-weight: 600;
  line-height: 1.4;
  text-align: left;
  color: var(--van-text-color, #323233);
  border: 1px solid var(--van-gray-3, #ebedf0);
  border-radius: 10px;
  background: var(--van-gray-2, #f2f3f5);
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}
.rule-card__shipper-chip:active {
  opacity: 0.92;
}
.rule-card__shipper-text {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.rule-card__shipper-caret {
  flex-shrink: 0;
  color: var(--van-text-color-2, #646566);
}
.rule-shipper-popover :deep(.van-popover__content) {
  padding: 0;
}
.rule-shipper-float {
  display: flex;
  flex-direction: column;
  width: min(88vw, 320px);
  max-height: min(52vh, 280px);
  overflow: hidden;
  border-radius: 12px;
  background: var(--van-background-2, #fff);
  box-shadow: 0 6px 20px rgba(15, 23, 42, 0.12);
}
.rule-shipper-float__head {
  flex-shrink: 0;
  padding: 10px 14px 6px;
  font-size: 14px;
  font-weight: 600;
  color: var(--van-text-color);
  border-bottom: 1px solid var(--van-border-color);
  background: var(--van-gray-2, #f2f3f5);
  border-radius: 12px 12px 0 0;
}
.rule-shipper-float__scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
  max-height: min(44vh, 240px);
}
.rule-shipper-float__scroll :deep(.van-cell) {
  background: var(--van-background-2, #fff);
}
.rule-card__line + .rule-card__line {
  border-top: 1px solid var(--van-border-color);
}
.rule-card__body {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 16px 10px;
}
.rule-card__chk {
  flex-shrink: 0;
  margin-top: 2px;
}
.rule-card__merge {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.rule-card__product-line {
  font-size: 15px;
  line-height: 1.4;
  font-weight: 600;
  word-break: break-word;
  color: #000;
}
.rule-card__price-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.rule-card__price-label {
  flex-shrink: 0;
  font-size: 15px;
  color: var(--van-text-color-2, #646566);
  font-weight: 400;
}
.rule-card__price-value {
  flex: 1;
  min-width: 0;
  text-align: right;
  font-size: 15px;
  font-weight: 600;
  color: #000;
  font-variant-numeric: tabular-nums;
}
.rule-card__field {
  flex: 1;
  min-width: 0;
  padding: 0;
}
.rule-card__field :deep(.van-cell) {
  padding: 0;
  background: transparent;
}
.rule-card__field :deep(.van-field__control) {
  color: #000;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.rule-card__field :deep(.van-field__control:read-only) {
  opacity: 1;
}
.rule-btns {
  display: flex;
  gap: 8px;
  padding: 10px 16px 12px;
  justify-content: flex-end;
  border-top: 1px solid var(--van-border-color);
}
.popup-title {
  font-weight: 600;
  text-align: center;
  margin-bottom: 8px;
}

/* 商品默认价：新建商品悬浮钮（替代 FloatingBubble，无磁吸小球） */
.prices-fab {
  position: fixed;
  right: 16px;
  bottom: calc(72px + env(safe-area-inset-bottom, 0px));
  z-index: 999;
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: var(--van-primary-color);
  color: var(--van-background-2, #fff);
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 14px rgba(25, 137, 250, 0.35);
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}
.prices-fab:active {
  opacity: 0.88;
}

.add-rule-popup {
  width: min(92vw, 400px);
  max-height: min(88vh, 520px);
}
.add-rule-dialog {
  padding: 14px 12px max(12px, env(safe-area-inset-bottom));
  max-height: min(85vh, 500px);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.add-rule-dialog__title {
  font-weight: 600;
  text-align: center;
  padding: 0 4px 12px;
  font-size: 16px;
  flex-shrink: 0;
}
.add-rule-dialog :deep(.van-cell-group) {
  overflow-y: auto;
  flex: 1;
  min-height: 0;
}
.add-rule-dialog__actions {
  padding: 12px 4px 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex-shrink: 0;
}

/* 仅中间列表滚动：Popup 根节点不滚动，内部仅 __scroll 可滚（插槽在 .van-popup 根上，无 __content） */
.batch-edit-popup.van-popup {
  width: min(94vw, 420px) !important;
  max-height: min(88vh, 560px) !important;
  height: min(88vh, 560px) !important;
  overflow: hidden !important;
  display: flex !important;
  flex-direction: column !important;
  box-sizing: border-box !important;
}
.batch-edit-dialog {
  flex: 1;
  min-height: 0;
  padding: 14px 12px max(12px, env(safe-area-inset-bottom));
  overflow: hidden;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}
.batch-edit-dialog__title {
  font-weight: 600;
  text-align: center;
  padding: 0 4px 8px;
  font-size: 16px;
  flex-shrink: 0;
}
.batch-edit-dialog__hint {
  margin: 0 4px 10px;
  font-size: 12px;
  line-height: 1.45;
  color: var(--van-text-color-2);
  flex-shrink: 0;
}
.batch-edit-dialog__scroll {
  flex: 1 1 0;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  -webkit-overflow-scrolling: touch;
  padding: 0 2px;
}
.batch-edit-row__meta {
  font-size: 12px;
  color: var(--van-text-color-2);
  padding: 8px 0 4px;
}
.batch-edit-row__sep {
  height: 1px;
  background: var(--van-border-color);
  margin: 10px 0 4px;
}
.batch-edit-dialog__actions {
  padding: 12px 4px 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex-shrink: 0;
  background: var(--van-background-2, #fff);
}
.batch-edit-name-wrap :deep(.van-field__control) {
  color: var(--batch-name-fg, #000) !important;
}
.batch-edit-price-wrap :deep(.van-field__control) {
  color: #000 !important;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.add-rule-product-name {
  font-size: 15px;
  line-height: 1.45;
  font-weight: 600;
}
.add-rule-product-placeholder {
  color: var(--van-field-placeholder-text-color, #c8c9cc);
  font-size: 15px;
}

.rule-edit-hint {
  margin: 0 16px 10px;
  font-size: 13px;
  line-height: 1.45;
  color: var(--van-text-color-2);
}
.rule-edit-hint__shipper {
  color: var(--van-text-color);
  font-weight: 500;
}
.rule-edit-hint__product {
  font-weight: 600;
}

.pick-p-list {
  max-height: min(55vh, 420px);
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
}
.pick-p-name {
  font-size: 15px;
  font-weight: 600;
  line-height: 1.35;
}
.pick-p-default-price {
  flex-shrink: 0;
  font-size: 14px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  color: var(--van-danger-color, #ee0a24);
}

.product-editor-popup {
  width: min(92vw, 400px);
  max-height: min(88vh, 560px);
}
.product-editor-dialog {
  padding: 14px 12px max(12px, env(safe-area-inset-bottom));
  max-height: min(85vh, 540px);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.product-editor-dialog__title {
  font-weight: 600;
  text-align: center;
  padding: 0 4px 10px;
  font-size: 16px;
  flex-shrink: 0;
}
.product-editor-dialog :deep(.van-cell-group) {
  overflow-y: auto;
  flex: 1;
  min-height: 0;
}
.product-editor-dialog__actions {
  padding: 12px 4px 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex-shrink: 0;
}
.up-preview {
  position: relative;
  width: 120px;
  max-width: 100%;
  aspect-ratio: 3 / 4;
  border-radius: 8px;
  overflow: hidden;
  background: var(--van-gray-2);
}
.up-preview img {
  position: absolute;
  inset: 0;
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: center;
  cursor: zoom-in;
}
.up-placeholder {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 8px;
  font-size: 12px;
  color: var(--van-text-color-3);
  text-align: center;
}
</style>
