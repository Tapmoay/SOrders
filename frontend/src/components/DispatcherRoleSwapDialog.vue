<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { showConfirmDialog, showFailToast, showLoadingToast, showSuccessToast, closeToast } from 'vant'

import {
  fetchUsers,
  invalidateDriversCache,
  swapShipperDriverRole,
  type UserListItem,
} from '@/api/user'
import { formatApiError } from '@/utils/apiError'

const props = defineProps<{
  show: boolean
}>()

const emit = defineEmits<{
  'update:show': [boolean]
  success: []
}>()

const visible = computed({
  get: () => props.show,
  set: (v: boolean) => emit('update:show', v),
})

const loading = ref(false)
const shippers = ref<UserListItem[]>([])
const drivers = ref<UserListItem[]>([])

const selectedShipperId = ref<number | null>(null)
const selectedDriverId = ref<number | null>(null)

const shipperPickerOpen = ref(false)
const driverPickerOpen = ref(false)
const shipperSearchQ = ref('')
const driverSearchQ = ref('')

const selectedShipper = computed(() => {
  if (selectedShipperId.value == null) return null
  return shippers.value.find((x) => x.id === selectedShipperId.value) ?? null
})

const selectedDriver = computed(() => {
  if (selectedDriverId.value == null) return null
  return drivers.value.find((x) => x.id === selectedDriverId.value) ?? null
})

/** 与后端 /users 返回的 role 对齐（兼容枚举名、大小写） */
function normalizeListRole(role: unknown): 'shipper' | 'driver' | 'dispatcher' | '' {
  const raw = String(role ?? '').trim()
  if (!raw) return ''
  const tail = raw.toLowerCase().split('.').pop() ?? ''
  if (tail === 'shipper' || tail === 'driver' || tail === 'dispatcher') {
    return tail as 'shipper' | 'driver' | 'dispatcher'
  }
  return ''
}

function matchUser(u: UserListItem, q: string): boolean {
  if (!q) return true
  const n = `${u.full_name ?? ''} ${u.phone ?? ''} ${u.username ?? ''}`.toLowerCase()
  return n.includes(q)
}

const filteredShippers = computed(() => {
  const q = shipperSearchQ.value.trim().toLowerCase()
  return shippers.value.filter((u) => matchUser(u, q))
})

const filteredDrivers = computed(() => {
  const q = driverSearchQ.value.trim().toLowerCase()
  return drivers.value.filter((u) => matchUser(u, q))
})

function syncSelectionAfterLoad() {
  if (shippers.value.length) {
    const ok =
      selectedShipperId.value != null &&
      shippers.value.some((s) => s.id === selectedShipperId.value)
    if (!ok) selectedShipperId.value = shippers.value[0]!.id
  } else {
    selectedShipperId.value = null
  }
  if (drivers.value.length) {
    const ok =
      selectedDriverId.value != null && drivers.value.some((s) => s.id === selectedDriverId.value)
    if (!ok) selectedDriverId.value = drivers.value[0]!.id
  } else {
    selectedDriverId.value = null
  }
}

async function loadLists() {
  loading.value = true
  try {
    // 一次拉全量用户再按角色拆分，避免按 role 查询在部分库/缓存下漏数据；打开时清司机缓存防陈旧
    invalidateDriversCache()
    const all = await fetchUsers({ limit: 500 }, true)
    const rows = Array.isArray(all) ? all : []
    shippers.value = rows.filter((u) => normalizeListRole(u.role) === 'shipper')
    drivers.value = rows.filter((u) => normalizeListRole(u.role) === 'driver')
    syncSelectionAfterLoad()
  } catch (e) {
    showFailToast(formatApiError(e, '加载用户列表失败'))
  } finally {
    loading.value = false
  }
}

watch(
  () => props.show,
  (open) => {
    if (open) void loadLists()
    else {
      shipperPickerOpen.value = false
      driverPickerOpen.value = false
    }
  },
)

watch(shipperPickerOpen, (open) => {
  if (open) shipperSearchQ.value = ''
})

watch(driverPickerOpen, (open) => {
  if (open) driverSearchQ.value = ''
})

function close() {
  emit('update:show', false)
}

function openShipperPicker() {
  shipperPickerOpen.value = true
}

function openDriverPicker() {
  driverPickerOpen.value = true
}

function pickShipper(u: UserListItem) {
  selectedShipperId.value = u.id
  shipperPickerOpen.value = false
}

function pickDriver(u: UserListItem) {
  selectedDriverId.value = u.id
  driverPickerOpen.value = false
}

async function toDriver(u: UserListItem) {
  try {
    await showConfirmDialog({
      title: '转为司机',
      message: `将「${u.full_name || u.phone}」由货主身份切换为司机身份？切换后可使用该账号登录司机端。`,
    })
  } catch {
    return
  }
  showLoadingToast({ message: '处理中…', forbidClick: true, duration: 0 })
  try {
    await swapShipperDriverRole(u.id)
    invalidateDriversCache()
    showSuccessToast('已切换为司机身份')
    await loadLists()
    emit('success')
  } catch (e) {
    showFailToast(formatApiError(e, '操作失败'))
  } finally {
    closeToast()
  }
}

async function toShipper(u: UserListItem) {
  try {
    await showConfirmDialog({
      title: '转为货主',
      message: `将「${u.full_name || u.phone}」由司机身份切换为货主身份？切换后可使用该账号登录货主端。`,
    })
  } catch {
    return
  }
  showLoadingToast({ message: '处理中…', forbidClick: true, duration: 0 })
  try {
    await swapShipperDriverRole(u.id)
    invalidateDriversCache()
    showSuccessToast('已切换为货主身份')
    await loadLists()
    emit('success')
  } catch (e) {
    showFailToast(formatApiError(e, '操作失败'))
  } finally {
    closeToast()
  }
}
</script>

<template>
  <van-popup
    v-model:show="visible"
    round
    position="center"
    teleport="body"
    class="role-swap-popup"
    :style="{ width: 'min(400px, 92vw)' }"
  >
    <div class="role-swap">
      <div class="role-swap__head">
        <span class="role-swap__title">身份指派</span>
        <button type="button" class="role-swap__close" aria-label="关闭" @click="close">×</button>
      </div>
      <p class="role-swap__hint">
        点击姓名可搜索并更换目标账号。将货主切换为司机（或反之）后需重新登录对应端。
      </p>

      <van-loading v-if="loading" class="role-swap__loading" vertical>加载中…</van-loading>

      <div v-else class="role-swap__scroll">
        <section class="role-swap__sec">
          <div class="role-swap__sec-title">货主 → 司机</div>
          <van-empty
            v-if="!shippers.length"
            image-size="56"
            description="暂无货主账号（可能已全部转为司机，或需在用户管理中新增）"
          />
          <div v-else class="role-swap__row">
            <div class="role-swap__meta">
              <button
                type="button"
                class="role-swap__name-btn"
                @click="openShipperPicker"
              >
                <span class="role-swap__name role-swap__name--link">{{
                  selectedShipper?.full_name || '货主'
                }}</span>
                <van-icon name="arrow-down" class="role-swap__name-caret" />
              </button>
              <span class="role-swap__phone">{{ selectedShipper?.phone ?? '—' }}</span>
            </div>
            <van-button
              size="small"
              type="primary"
              plain
              :disabled="!selectedShipper"
              @click="selectedShipper && toDriver(selectedShipper)"
            >
              转为司机
            </van-button>
          </div>
        </section>

        <section class="role-swap__sec">
          <div class="role-swap__sec-title">司机 → 货主</div>
          <van-empty
            v-if="!drivers.length"
            image-size="56"
            description="暂无司机账号（可能已全部转为货主，或需在用户管理中新增）"
          />
          <div v-else class="role-swap__row">
            <div class="role-swap__meta">
              <button type="button" class="role-swap__name-btn" @click="openDriverPicker">
                <span class="role-swap__name role-swap__name--link">{{
                  selectedDriver?.full_name || '司机'
                }}</span>
                <van-icon name="arrow-down" class="role-swap__name-caret" />
              </button>
              <span class="role-swap__phone">{{ selectedDriver?.phone ?? '—' }}</span>
            </div>
            <van-button
              size="small"
              type="warning"
              plain
              :disabled="!selectedDriver"
              @click="selectedDriver && toShipper(selectedDriver)"
            >
              转为货主
            </van-button>
          </div>
        </section>
      </div>
    </div>
  </van-popup>

  <!-- 选择货主：小尺寸居中浮窗 -->
  <van-popup
    v-model:show="shipperPickerOpen"
    position="center"
    round
    teleport="body"
    class="pick-mini-popup"
    :z-index="3000"
    :style="{ width: 'min(300px, 88vw)' }"
  >
    <div class="pick-mini">
      <div class="pick-mini__head">
        <span class="pick-mini__title">选择货主</span>
        <button type="button" class="pick-mini__close" aria-label="关闭" @click="shipperPickerOpen = false">
          ×
        </button>
      </div>
      <van-search
        v-model="shipperSearchQ"
        placeholder="搜索姓名、手机号"
        class="pick-mini__search"
      />
      <div class="pick-mini__scroll">
        <button
          v-for="u in filteredShippers"
          :key="u.id"
          type="button"
          class="pick-mini__row"
          @click="pickShipper(u)"
        >
          <div class="pick-mini__text">
            <span class="pick-mini__name">{{ u.full_name || '货主' }}</span>
            <span class="pick-mini__phone">{{ u.phone }}</span>
          </div>
          <van-icon v-if="u.id === selectedShipperId" name="success" class="pick-mini__ok" />
        </button>
        <van-empty v-if="!filteredShippers.length" image-size="48" description="无匹配货主" />
      </div>
    </div>
  </van-popup>

  <!-- 选择司机：小尺寸居中浮窗 -->
  <van-popup
    v-model:show="driverPickerOpen"
    position="center"
    round
    teleport="body"
    class="pick-mini-popup"
    :z-index="3000"
    :style="{ width: 'min(300px, 88vw)' }"
  >
    <div class="pick-mini">
      <div class="pick-mini__head">
        <span class="pick-mini__title">选择司机</span>
        <button type="button" class="pick-mini__close" aria-label="关闭" @click="driverPickerOpen = false">
          ×
        </button>
      </div>
      <van-search v-model="driverSearchQ" placeholder="搜索姓名、手机号" class="pick-mini__search" />
      <div class="pick-mini__scroll">
        <button
          v-for="u in filteredDrivers"
          :key="u.id"
          type="button"
          class="pick-mini__row"
          @click="pickDriver(u)"
        >
          <div class="pick-mini__text">
            <span class="pick-mini__name">{{ u.full_name || '司机' }}</span>
            <span class="pick-mini__phone">{{ u.phone }}</span>
          </div>
          <van-icon v-if="u.id === selectedDriverId" name="success" class="pick-mini__ok" />
        </button>
        <van-empty v-if="!filteredDrivers.length" image-size="48" description="无匹配司机" />
      </div>
    </div>
  </van-popup>
</template>

<style scoped>
.role-swap {
  max-height: min(72vh, 620px);
  display: flex;
  flex-direction: column;
  padding: 0 0 12px;
}
.role-swap__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px 8px;
  border-bottom: 1px solid var(--van-border-color);
}
.role-swap__title {
  font-size: 17px;
  font-weight: 600;
  color: var(--van-text-color);
}
.role-swap__close {
  width: 36px;
  height: 36px;
  margin: -6px -8px -6px 0;
  font-size: 22px;
  line-height: 1;
  color: var(--van-text-color-2);
  background: none;
  border: none;
  cursor: pointer;
  border-radius: 8px;
}
.role-swap__close:active {
  background: rgba(0, 0, 0, 0.06);
}
.role-swap__hint {
  margin: 0;
  padding: 10px 16px 12px;
  font-size: 13px;
  line-height: 1.55;
  color: var(--van-text-color-2);
}
.role-swap__loading {
  padding: 32px 0;
}
.role-swap__scroll {
  overflow-y: auto;
  padding: 0 12px;
  flex: 1;
  min-height: 0;
}
.role-swap__sec {
  margin-bottom: 16px;
}
.role-swap__sec-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--van-text-color-3);
  padding: 8px 4px 10px;
}
.role-swap__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 10px;
  margin-bottom: 8px;
  background: var(--van-background-2, #f7f8fa);
  border-radius: 10px;
  border: 1px solid var(--van-border-color);
}
.role-swap__meta {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  align-items: flex-start;
}
.role-swap__name-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  max-width: 100%;
  padding: 0;
  margin: 0;
  background: none;
  border: none;
  cursor: pointer;
  text-align: left;
  -webkit-tap-highlight-color: transparent;
}
.role-swap__name-btn:active .role-swap__name--link {
  opacity: 0.75;
}
.role-swap__name {
  font-size: 15px;
  font-weight: 500;
  color: var(--van-text-color);
}
.role-swap__name--link {
  color: var(--van-primary-color);
  text-decoration: underline;
  text-underline-offset: 3px;
}
.role-swap__name-caret {
  flex-shrink: 0;
  font-size: 14px;
  color: var(--van-primary-color);
}
.role-swap__phone {
  font-size: 12px;
  color: var(--van-text-color-2);
}

.pick-mini {
  max-height: min(52vh, 420px);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding-bottom: 8px;
}
.pick-mini__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px 8px;
  border-bottom: 1px solid var(--van-border-color);
}
.pick-mini__title {
  font-size: 16px;
  font-weight: 600;
  color: var(--van-text-color);
}
.pick-mini__close {
  width: 34px;
  height: 34px;
  margin: -4px -6px -4px 0;
  font-size: 22px;
  line-height: 1;
  color: var(--van-text-color-2);
  background: none;
  border: none;
  cursor: pointer;
  border-radius: 8px;
}
.pick-mini__close:active {
  background: rgba(0, 0, 0, 0.06);
}
.pick-mini__search {
  padding: 6px 10px 4px;
}
.pick-mini__search :deep(.van-field__control) {
  font-size: 14px;
}
.pick-mini__scroll {
  max-height: min(38vh, 280px);
  overflow-y: auto;
  padding: 4px 8px 12px;
}
.pick-mini__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
  padding: 10px 8px;
  border: none;
  border-radius: 8px;
  background: transparent;
  cursor: pointer;
  text-align: left;
  -webkit-tap-highlight-color: transparent;
}
.pick-mini__row:active {
  background: rgba(0, 0, 0, 0.05);
}
.pick-mini__text {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.pick-mini__name {
  font-size: 16px;
  font-weight: 600;
  color: #0a0a0a;
  line-height: 1.35;
}
.pick-mini__phone {
  font-size: 12px;
  color: #8c8c8c;
  font-weight: 400;
}
.pick-mini__ok {
  flex-shrink: 0;
  color: var(--van-primary-color);
  font-size: 18px;
}
</style>

<style>
.role-swap-popup.van-popup--center,
.pick-mini-popup.van-popup--center {
  overflow: hidden;
}
</style>
