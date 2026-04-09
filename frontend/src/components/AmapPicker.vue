<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { showFailToast } from 'vant'

const props = withDefaults(
  defineProps<{
    show: boolean
    /** 打开地图时居中到该点（如编辑已有地址） */
    initialLngLat?: { lng: number; lat: number } | null
    panelTitle?: string
  }>(),
  {
    initialLngLat: null,
    panelTitle: '地图选点',
  },
)

const emit = defineEmits<{
  'update:show': [v: boolean]
  confirm: [payload: { address: string; lng: number; lat: number }]
}>()

const mapEl = ref<HTMLDivElement | null>(null)
const loading = ref(false)
const pickedAddress = ref('')
const pickedLng = ref<number | null>(null)
const pickedLat = ref<number | null>(null)

const amapKey = import.meta.env.VITE_AMAP_KEY || ''
const securityCode = import.meta.env.VITE_AMAP_SECURITY_JS_CODE || ''

function loadScript(): Promise<void> {
  const w = window as unknown as { AMap?: unknown }
  if (w.AMap) return Promise.resolve()
  return new Promise((resolve, reject) => {
    const s = document.createElement('script')
    s.src = `https://webapi.amap.com/maps?v=2.0&key=${amapKey}&plugin=AMap.Geocoder`
    s.async = true
    s.onload = () => resolve()
    s.onerror = () => reject(new Error('map script'))
    document.head.appendChild(s)
  })
}

function initMap() {
  const init = props.initialLngLat
  const w = window as unknown as {
    AMap: {
      Map: new (el: HTMLElement, opts: { zoom: number; center: number[] }) => {
        on: (ev: string, fn: (e: { lnglat: { lng: number; lat: number } }) => void) => void
        remove: (m: unknown) => void
      }
      plugin: (names: string | string[], cb: () => void) => void
      Geocoder: new () => {
        getAddress: (
          lnglat: number[] | { lng: number; lat: number },
          cb: (status: string, result: { regeocode?: { formattedAddress?: string } }) => void,
        ) => void
      }
      Marker: new (opts: { position: number[]; map: unknown }) => unknown
    }
    _AMapSecurityConfig?: { securityJsCode: string }
  }
  if (securityCode) {
    w._AMapSecurityConfig = { securityJsCode: securityCode }
  }
  const AMap = w.AMap
  const el = mapEl.value
  if (!el || !AMap) return

  const center: [number, number] = init
    ? [init.lng, init.lat]
    : [116.397428, 39.90923]
  const map = new AMap.Map(el, { zoom: init ? 16 : 14, center })
  let marker: unknown = null

  AMap.plugin('AMap.Geocoder', () => {
    const geocoder = new AMap.Geocoder()
    const applyPoint = (lng: number, lat: number, moveMarker: boolean) => {
      pickedLng.value = lng
      pickedLat.value = lat
      if (moveMarker) {
        if (marker) {
          ;(map as { remove: (m: unknown) => void }).remove(marker)
        }
        marker = new AMap.Marker({ position: [lng, lat], map })
      }
      geocoder.getAddress([lng, lat], (status, result) => {
        if (status === 'complete' && result?.regeocode?.formattedAddress) {
          pickedAddress.value = result.regeocode.formattedAddress
        } else {
          pickedAddress.value = `${lng.toFixed(5)}, ${lat.toFixed(5)}`
        }
      })
    }

    if (init) {
      applyPoint(init.lng, init.lat, true)
    }

    map.on('click', (e: { lnglat: { lng: number; lat: number } }) => {
      const lng = e.lnglat.lng
      const lat = e.lnglat.lat
      applyPoint(lng, lat, true)
    })
  })
}

watch(
  () => props.show,
  async (v) => {
    if (!v) return
    if (!amapKey) {
      showFailToast('未配置 VITE_AMAP_KEY')
      emit('update:show', false)
      return
    }
    loading.value = true
    pickedAddress.value = ''
    pickedLng.value = null
    pickedLat.value = null
    try {
      await loadScript()
      await nextTick()
      if (mapEl.value) mapEl.value.innerHTML = ''
      initMap()
    } catch {
      showFailToast('地图加载失败')
      emit('update:show', false)
    } finally {
      loading.value = false
    }
  },
)

function onClose() {
  emit('update:show', false)
}

function onConfirm() {
  if (pickedLng.value == null || pickedLat.value == null || !pickedAddress.value) {
    showFailToast('请在地图上点击选择位置')
    return
  }
  emit('confirm', {
    address: pickedAddress.value,
    lng: pickedLng.value,
    lat: pickedLat.value,
  })
  emit('update:show', false)
}
</script>

<template>
  <van-popup
    :show="show"
    position="bottom"
    round
    :style="{ height: '85%', width: '100%', maxWidth: '480px', margin: '0 auto' }"
    @update:show="emit('update:show', $event)"
  >
    <div class="amap-head">
      <span class="title">{{ panelTitle }}</span>
      <van-button size="small" @click="onClose">关闭</van-button>
    </div>
    <div v-show="loading" class="amap-loading">加载中…</div>
    <div ref="mapEl" class="amap-box" />
    <div class="amap-addr">{{ pickedAddress || '点击地图选择位置' }}</div>
    <div class="amap-actions">
      <van-button type="primary" block round :disabled="!pickedAddress" @click="onConfirm">使用该地址</van-button>
    </div>
  </van-popup>
</template>

<style scoped>
.amap-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--van-border-color);
}
.title {
  font-weight: 600;
}
.amap-box {
  width: 100%;
  height: 45vh;
  min-height: 240px;
}
.amap-loading {
  padding: 12px;
  text-align: center;
  color: var(--van-text-color-2);
}
.amap-addr {
  padding: 10px 16px;
  font-size: 13px;
  color: var(--van-text-color);
  line-height: 1.4;
  max-height: 72px;
  overflow: auto;
}
.amap-actions {
  padding: 12px 16px max(12px, env(safe-area-inset-bottom));
}
</style>
