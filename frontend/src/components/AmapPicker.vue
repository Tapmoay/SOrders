<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { showFailToast } from 'vant'

/** 本会话内已同意地图自动定位（避免每次打开都弹） */
const LOC_CONSENT_KEY = 'sorders_map_location_consent'

/** 江西省上饶市鄱阳县 — 默认地图中心（GCJ-02），无具体坐标/地址时使用 */
const POYANG_DEFAULT_CENTER: [number, number] = [116.704, 29.011]
const POYANG_DEFAULT_ZOOM = 11
/**
 * 县域内两个常用镇区中心（GCJ-02），用于快捷区域与细化视野。
 * 田畈街镇：维基坐标约 116°52′E / 29°21′N；金盘岭镇：公开地图约 117.001°E / 29.334°N。
 */
const POYANG_SUB_TIANFAN_CENTER: [number, number] = [116.8697, 29.3528]
const POYANG_SUB_JINPANLING_CENTER: [number, number] = [117.0013, 29.3343]
const POYANG_SUB_AREA_ZOOM = 13
/**
 * 地理编码与 POI 搜索的行政范围（高德 city：县名 + citylimit 限制在县域内）
 */
const POYANG_SEARCH_REGION = '鄱阳县'

/** 用户只填村/镇片段时，补全为可地理编码的地址 */
function expandPoyangLocalAddressForGeocode(addr: string): string {
  const t = addr.trim()
  if (!t) return t
  if (/鄱阳县|上饶市|江西省/.test(t)) return t
  if (/田畈街|金盘岭/.test(t)) return `江西省上饶市鄱阳县${t}`
  return t
}

type SearchHit = { name: string; address: string; lng: number; lat: number; regionHint?: string }

/** 单字镇名搜索时补全为「××镇」，提高 POI 命中率 */
function normalizePlaceSearchKeyword(kw: string): string {
  const k = kw.trim()
  if (k === '田畈街') return '田畈街镇'
  if (k === '金盘岭') return '金盘岭镇'
  return k
}

/**
 * 已写明在田畈街/金盘岭其一则不再拆成两镇搜；
 * 村落等本地小地名（含村/寨/庄/组）时，优先在田畈街镇、金盘岭镇两侧并行检索或依次地理编码。
 */
function shouldBiasPoyangSubTowns(kw: string): boolean {
  const t = kw.trim()
  if (!t) return false
  if (/田畈街|金盘岭/.test(t)) return false
  return /[村村寨寨庄莊组組]/.test(t)
}

function mergeDedupeSearchHits(a: SearchHit[], b: SearchHit[]): SearchHit[] {
  const seen = new Set<string>()
  const out: SearchHit[] = []
  for (const h of [...a, ...b]) {
    const k = `${h.lng.toFixed(5)}_${h.lat.toFixed(5)}_${h.name}`
    if (seen.has(k)) continue
    seen.add(k)
    out.push(h)
  }
  return out
}

function isMobileLike(): boolean {
  if (typeof navigator === 'undefined') return false
  const ua = navigator.userAgent
  if (/Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(ua)) return true
  return typeof window !== 'undefined' && window.matchMedia?.('(max-width: 768px)')?.matches === true
}

const props = withDefaults(
  defineProps<{
    show: boolean
    /** 打开地图时居中到该点（如已有经纬度） */
    initialLngLat?: { lng: number; lat: number } | null
    /**
     * 无经纬度时：把用户填写的地址交给高德地理编码后居中。
     * 与 initialLngLat 同时有时以经纬度为准。
     */
    initialAddress?: string | null
    panelTitle?: string
  }>(),
  {
    initialLngLat: null,
    initialAddress: null,
    panelTitle: '地图选点',
  },
)

const emit = defineEmits<{
  'update:show': [v: boolean]
  confirm: [payload: { address: string; lng: number; lat: number }]
}>()

const mapEl = ref<HTMLDivElement | null>(null)
let mapResizeObserver: ResizeObserver | null = null
let mapOpenFallbackTimer: ReturnType<typeof setTimeout> | null = null
let mapInitInFlight: Promise<void> | null = null
const amapMap = ref<{ resize: () => void; setCenter: (c: number[]) => void; setZoom: (z: number) => void } | null>(
  null,
)
const loading = ref(false)
const positioning = ref(false)
const pickedAddress = ref('')
const pickedLng = ref<number | null>(null)
const pickedLat = ref<number | null>(null)

const searchKeyword = ref('')
const searchHits = ref<SearchHit[]>([])

/** 由 initMap 赋值：同意/重试时执行实际定位 */
let runGeolocationInnerFn: (() => void) | null = null
let finishInitialFn: (() => void) | null = null
/** 用户点击「定位到当前」时走与此前一致的同意流程 */
let requestLocateWithConsentFn: (() => void) | null = null

const showLocConsentDialog = ref(false)
const showLocFailDialog = ref(false)

const amapKey = import.meta.env.VITE_AMAP_KEY || ''
const securityCode = import.meta.env.VITE_AMAP_SECURITY_JS_CODE || ''

/** 从高德返回的 location 上取经纬度 */
function lngLatFromLocation(loc: unknown): { lng: number; lat: number } | null {
  if (loc == null) return null
  if (Array.isArray(loc) && loc.length >= 2) {
    const lng = Number(loc[0])
    const lat = Number(loc[1])
    return Number.isFinite(lng) && Number.isFinite(lat) ? { lng, lat } : null
  }
  const o = loc as { lng?: number; lat?: number; getLng?: () => number; getLat?: () => number }
  if (typeof o.getLng === 'function' && typeof o.getLat === 'function') {
    return { lng: o.getLng(), lat: o.getLat() }
  }
  if (typeof o.lng === 'number' && typeof o.lat === 'number') {
    return { lng: o.lng, lat: o.lat }
  }
  return null
}

function scheduleMapResize() {
  const m = amapMap.value
  if (!m) return
  const run = () => {
    try {
      ;(m as { resize?: () => void }).resize?.()
    } catch {
      /* ignore */
    }
  }
  run()
  requestAnimationFrame(run)
  setTimeout(run, 100)
  setTimeout(run, 350)
}

function detachMapResizeObserver() {
  mapResizeObserver?.disconnect()
  mapResizeObserver = null
}

/** 弹层内地图容器在 flex 下可能晚于脚本就绪才有宽高，需等到可见再 new AMap.Map */
async function waitMapContainerReady(): Promise<void> {
  for (let i = 0; i < 30; i++) {
    await nextTick()
    const el = mapEl.value
    if (el && el.offsetWidth > 0 && el.offsetHeight > 0) return
    await new Promise<void>((r) => setTimeout(r, 50))
  }
}

function loadScript(): Promise<void> {
  const w = window as unknown as { AMap?: unknown; _AMapSecurityConfig?: { securityJsCode: string } }
  if (w.AMap) return Promise.resolve()
  w._AMapSecurityConfig = { securityJsCode: securityCode }
  const plugins = ['AMap.Geocoder', 'AMap.Geolocation', 'AMap.PlaceSearch'].join(',')
  return new Promise((resolve, reject) => {
    const s = document.createElement('script')
    s.src = `https://webapi.amap.com/maps?v=2.0&key=${amapKey}&plugin=${encodeURIComponent(plugins)}`
    s.async = true
    s.onload = () => resolve()
    s.onerror = () => reject(new Error('map script'))
    document.head.appendChild(s)
  })
}

function initMap() {
  const initCoord = props.initialLngLat
  const initAddr = props.initialAddress?.trim() || ''

  const w = window as unknown as {
    AMap: {
      Map: new (
        el: HTMLElement,
        opts: { zoom: number; center: number[] },
      ) => {
        on: (ev: string, fn: (e: { lnglat: { lng: number; lat: number } }) => void) => void
        remove: (m: unknown) => void
        setCenter: (c: number[]) => void
        setZoom: (z: number) => void
      }
      plugin: (names: string | string[], cb: () => void) => void
      Geocoder: new (opts?: { city?: string }) => {
        getAddress: (
          lnglat: number[] | { lng: number; lat: number },
          cb: (status: string, result: { regeocode?: { formattedAddress?: string } }) => void,
        ) => void
        getLocation: (
          address: string,
          cb: (
            status: string,
            result: { geocodes?: Array<{ location: unknown }> },
          ) => void,
        ) => void
      }
      Geolocation: new (opts?: Record<string, unknown>) => {
        getCurrentPosition: (cb: (status: string, result: { position?: unknown }) => void) => void
      }
      PlaceSearch: new (opts?: { pageSize?: number; city?: string; citylimit?: boolean; map?: unknown }) => {
        search: (
          keyword: string,
          cb: (
            status: string,
            result: { poiList?: { pois?: Array<{ name: string; address?: string; location: unknown }> } },
          ) => void,
        ) => void
      }
      Marker: new (opts: { position: number[]; map: unknown }) => unknown
    }
  }
  const AMap = w.AMap
  const el = mapEl.value
  if (!el || !AMap) return

  const center: [number, number] = [...POYANG_DEFAULT_CENTER]
  const map = new AMap.Map(el, { zoom: POYANG_DEFAULT_ZOOM, center })
  amapMap.value = map as unknown as typeof amapMap.value
  let marker: unknown = null

  AMap.plugin(['AMap.Geocoder', 'AMap.Geolocation', 'AMap.PlaceSearch'], () => {
    const geocoder = new AMap.Geocoder({ city: POYANG_SEARCH_REGION })
    const placeSearch = new AMap.PlaceSearch({
      pageSize: 15,
      city: POYANG_SEARCH_REGION,
      /** 仅在鄱阳县内检索 POI，与业务配送范围一致 */
      citylimit: true,
      map,
    })
    const geolocate = new AMap.Geolocation({
      enableHighAccuracy: true,
      /** 弱网/室内适当延长，避免过早失败 */
      timeout: 20000,
      maximumAge: 0,
      /** 转为 GCJ-02，与地图一致 */
      convert: true,
      showButton: false,
      showMarker: false,
      showCircle: false,
      needAddress: false,
    })

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
    applyPointRef = applyPoint

    const finishInitial = () => {
      positioning.value = false
      scheduleMapResize()
    }

    const runGeolocationInner = () => {
      positioning.value = true

      const applyLoc = (lng: number, lat: number) => {
        map.setCenter([lng, lat])
        map.setZoom(16)
        applyPoint(lng, lat, true)
      }

      /** 高德插件定位（融合 IP 等，作兜底） */
      const tryAmapGeolocation = () => {
        geolocate.getCurrentPosition((status, result) => {
          const loc = result?.position != null ? lngLatFromLocation(result.position) : null
          if (status === 'complete' && loc) {
            applyLoc(loc.lng, loc.lat)
          } else {
            showLocFailDialog.value = true
          }
          finishInitial()
        })
      }

      /**
       * 优先走浏览器原生定位（手机 GPS/Wi‑Fi 常见，成功率高于仅插件）。
       * WGS84 → GCJ-02 必须用 convertFrom，否则国内地图会偏几百米。
       */
      const AMapRoot = w.AMap as {
        convertFrom?: (
          lnglat: number[],
          type: string,
          cb: (status: string, result: { info?: string; locations?: unknown[] }) => void,
        ) => void
      }
      if (typeof navigator !== 'undefined' && navigator.geolocation) {
        navigator.geolocation.getCurrentPosition(
          (pos) => {
            const wgsLng = pos.coords.longitude
            const wgsLat = pos.coords.latitude
            if (typeof AMapRoot.convertFrom === 'function') {
              AMapRoot.convertFrom([wgsLng, wgsLat], 'gps', (_st, cvt) => {
                const ll = cvt?.locations?.[0] ? lngLatFromLocation(cvt.locations[0]) : null
                if (ll) {
                  applyLoc(ll.lng, ll.lat)
                  finishInitial()
                  return
                }
                tryAmapGeolocation()
              })
            } else {
              tryAmapGeolocation()
            }
          },
          () => tryAmapGeolocation(),
          { enableHighAccuracy: true, timeout: 25000, maximumAge: 0 },
        )
      } else {
        tryAmapGeolocation()
      }
    }

    runGeolocationInnerFn = runGeolocationInner

    /** 移动端首次需同意；桌面端或已同意则直接定位 */
    const requestGeolocationWithConsent = () => {
      finishInitialFn = finishInitial
      let consented = false
      try {
        consented = sessionStorage.getItem(LOC_CONSENT_KEY) === '1'
      } catch {
        consented = false
      }
      if (isMobileLike() && !consented) {
        showLocConsentDialog.value = true
      } else {
        runGeolocationInner()
      }
    }

    requestLocateWithConsentFn = requestGeolocationWithConsent

    const tryGeocodeAddress = (addr: string) => {
      positioning.value = true
      const raw = addr.trim()

      const finishFail = () => {
        map.setCenter([...POYANG_DEFAULT_CENTER])
        map.setZoom(POYANG_DEFAULT_ZOOM)
        finishInitial()
      }

      const applyOk = (lng: number, lat: number) => {
        map.setCenter([lng, lat])
        map.setZoom(16)
        applyPoint(lng, lat, true)
        finishInitial()
      }

      /** 村落名未带镇名时：先田畈街镇、再金盘岭镇尝试地理编码 */
      if (shouldBiasPoyangSubTowns(raw)) {
        const variants = [
          `江西省上饶市鄱阳县田畈街镇${raw}`,
          `江西省上饶市鄱阳县金盘岭镇${raw}`,
        ]
        let i = 0
        const tryNext = () => {
          if (i >= variants.length) {
            finishFail()
            return
          }
          geocoder.getLocation(variants[i++], (status, result) => {
            const first = result?.geocodes?.[0]
            const loc = first ? lngLatFromLocation(first.location) : null
            if (status === 'complete' && loc) {
              applyOk(loc.lng, loc.lat)
            } else {
              tryNext()
            }
          })
        }
        tryNext()
        return
      }

      geocoder.getLocation(expandPoyangLocalAddressForGeocode(addr), (status, result) => {
        const first = result?.geocodes?.[0]
        const loc = first ? lngLatFromLocation(first.location) : null
        if (status === 'complete' && loc) {
          applyOk(loc.lng, loc.lat)
        } else {
          finishFail()
        }
      })
    }

    if (initCoord) {
      map.setCenter([initCoord.lng, initCoord.lat])
      map.setZoom(16)
      applyPoint(initCoord.lng, initCoord.lat, true)
      finishInitial()
    } else if (initAddr) {
      tryGeocodeAddress(initAddr)
    } else {
      finishInitial()
    }

    map.on('click', (e: { lnglat: { lng: number; lat: number } }) => {
      const lng = e.lnglat.lng
      const lat = e.lnglat.lat
      applyPoint(lng, lat, true)
    })

    panToPoyangSubAreaImpl = (id) => {
      if (id === 'county') {
        map.setCenter([...POYANG_DEFAULT_CENTER])
        map.setZoom(POYANG_DEFAULT_ZOOM)
      } else if (id === 'tianfan') {
        map.setCenter([...POYANG_SUB_TIANFAN_CENTER])
        map.setZoom(POYANG_SUB_AREA_ZOOM)
      } else {
        map.setCenter([...POYANG_SUB_JINPANLING_CENTER])
        map.setZoom(POYANG_SUB_AREA_ZOOM)
      }
      scheduleMapResize()
    }

    runPlaceSearchImpl = (keyword: string) => {
      const kw = normalizePlaceSearchKeyword(keyword)
      if (!kw) {
        showFailToast('请输入搜索关键词')
        return
      }

      type PoiRow = { name: string; address?: string; location: unknown }
      const poisToHits = (pois: PoiRow[] | undefined, regionHint?: string): SearchHit[] => {
        if (!pois?.length) return []
        return pois
          .map((p) => {
            const ll = lngLatFromLocation(p.location)
            if (!ll) return null
            const h: SearchHit = {
              name: p.name || '地点',
              address: (p.address || '').trim(),
              lng: ll.lng,
              lat: ll.lat,
            }
            if (regionHint) h.regionHint = regionHint
            return h
          })
          .filter((x): x is SearchHit => x != null)
      }

      if (!shouldBiasPoyangSubTowns(kw)) {
        placeSearch.search(kw, (status, result) => {
          const pois = result?.poiList?.pois
          if (status !== 'complete' || !pois?.length) {
            searchHits.value = []
            showFailToast('未找到相关地点')
            return
          }
          const hits = poisToHits(pois)
          if (!hits.length) {
            searchHits.value = []
            showFailToast('未找到有效坐标')
            return
          }
          searchHits.value = hits
          scheduleMapResize()
        })
        return
      }

      let tHits: SearchHit[] = []
      let jHits: SearchHit[] = []
      let n = 0
      const onBothDone = () => {
        n += 1
        if (n < 2) return
        const merged = mergeDedupeSearchHits(tHits, jHits)
        searchHits.value = merged
        if (!merged.length) {
          showFailToast('未找到相关地点')
          return
        }
        scheduleMapResize()
      }

      placeSearch.search(`${kw} 田畈街镇`, (status, result) => {
        if (status === 'complete' && result?.poiList?.pois?.length) {
          tHits = poisToHits(result.poiList.pois, '田畈街镇')
        } else {
          tHits = []
        }
        onBothDone()
      })
      placeSearch.search(`${kw} 金盘岭镇`, (status, result) => {
        if (status === 'complete' && result?.poiList?.pois?.length) {
          jHits = poisToHits(result.poiList.pois, '金盘岭镇')
        } else {
          jHits = []
        }
        onBothDone()
      })
    }
  })
}

/** 由 initMap 内赋值 */
let runPlaceSearchImpl: ((keyword: string) => void) | null = null
let applyPointRef: ((lng: number, lat: number, moveMarker: boolean) => void) | null = null
let panToPoyangSubAreaImpl: ((id: 'county' | 'tianfan' | 'jinpanling') => void) | null = null

function onSearchSubmit() {
  if (!runPlaceSearchImpl) {
    showFailToast('地图未就绪')
    return
  }
  runPlaceSearchImpl(searchKeyword.value)
}

function onPoyangSubArea(id: 'county' | 'tianfan' | 'jinpanling') {
  if (!panToPoyangSubAreaImpl) {
    showFailToast('地图未就绪')
    return
  }
  panToPoyangSubAreaImpl(id)
}

function onPickSearchHit(hit: SearchHit) {
  const m = amapMap.value
  if (m) {
    m.setCenter([hit.lng, hit.lat])
    m.setZoom(17)
  }
  searchHits.value = []
  searchKeyword.value = hit.name
  applyPointRef?.(hit.lng, hit.lat, true)
  scheduleMapResize()
}

function onLocConsentConfirm() {
  try {
    sessionStorage.setItem(LOC_CONSENT_KEY, '1')
  } catch {
    /* 无痕模式等 */
  }
  showLocConsentDialog.value = false
  runGeolocationInnerFn?.()
}

function onLocConsentCancel() {
  showLocConsentDialog.value = false
  finishInitialFn?.()
}

function onLocFailRetry() {
  showLocFailDialog.value = false
  runGeolocationInnerFn?.()
}

function onLocFailDismiss() {
  showLocFailDialog.value = false
}

function onClickCurrentLocation() {
  if (!requestLocateWithConsentFn) {
    showFailToast('地图未就绪')
    return
  }
  requestLocateWithConsentFn()
}

watch(
  () => props.show,
  (v) => {
    if (!v) {
      if (mapOpenFallbackTimer != null) {
        clearTimeout(mapOpenFallbackTimer)
        mapOpenFallbackTimer = null
      }
      mapInitInFlight = null
      detachMapResizeObserver()
      amapMap.value = null
      runPlaceSearchImpl = null
      applyPointRef = null
      panToPoyangSubAreaImpl = null
      runGeolocationInnerFn = null
      finishInitialFn = null
      requestLocateWithConsentFn = null
      showLocConsentDialog.value = false
      showLocFailDialog.value = false
      searchKeyword.value = ''
      searchHits.value = []
      positioning.value = false
      loading.value = false
      return
    }
    if (!amapKey) {
      showFailToast('未配置 VITE_AMAP_KEY（仅写在本地 .env，勿提交仓库）')
      emit('update:show', false)
      return
    }
    if (!securityCode) {
      showFailToast(
        'JS API 2.0 须配置 VITE_AMAP_SECURITY_JS_CODE：高德控制台 Key 的「安全密钥」，写入本地 .env',
      )
      emit('update:show', false)
      return
    }
    positioning.value = false
    pickedAddress.value = ''
    pickedLng.value = null
    pickedLat.value = null
    searchKeyword.value = ''
    searchHits.value = []
    loading.value = true
    /** 部分环境下 @opened 不触发：延迟兜底再拉一次地图 */
    mapOpenFallbackTimer = setTimeout(() => {
      mapOpenFallbackTimer = null
      if (props.show && !amapMap.value) {
        void bootstrapMapInPopup()
      }
    }, 600)
  },
)

onBeforeUnmount(() => {
  if (mapOpenFallbackTimer != null) clearTimeout(mapOpenFallbackTimer)
  detachMapResizeObserver()
})

/**
 * 弹层打开后再初始化地图；送达地址地理编码在 initMap 内按 props.initialAddress 执行。
 */
async function bootstrapMapInPopup() {
  if (!props.show || !amapKey || !securityCode) return
  if (amapMap.value) return
  if (mapInitInFlight) {
    await mapInitInFlight
    return
  }

  mapInitInFlight = (async () => {
    loading.value = true
    try {
      await loadScript()
      await waitMapContainerReady()
      if (!props.show) return
      if (mapEl.value) mapEl.value.innerHTML = ''
      initMap()
      if (mapEl.value && typeof ResizeObserver !== 'undefined') {
        detachMapResizeObserver()
        mapResizeObserver = new ResizeObserver(() => scheduleMapResize())
        mapResizeObserver.observe(mapEl.value)
      }
      scheduleMapResize()
      setTimeout(() => scheduleMapResize(), 200)
      setTimeout(() => scheduleMapResize(), 500)
    } catch {
      showFailToast('地图加载失败')
      emit('update:show', false)
    } finally {
      loading.value = false
      mapInitInFlight = null
    }
  })()

  await mapInitInFlight
}

function onPopupOpened() {
  if (mapOpenFallbackTimer != null) {
    clearTimeout(mapOpenFallbackTimer)
    mapOpenFallbackTimer = null
  }
  void bootstrapMapInPopup()
}

function onClose() {
  emit('update:show', false)
}

function onConfirm() {
  const lng = pickedLng.value
  const lat = pickedLat.value
  if (lng == null || lat == null) {
    showFailToast('请在地图上点击选择位置，或搜索后选择结果')
    return
  }
  const address = pickedAddress.value.trim() || `${lng.toFixed(6)}, ${lat.toFixed(6)}`
  emit('confirm', {
    address,
    lng,
    lat,
  })
  emit('update:show', false)
}
</script>

<template>
  <van-popup
    class="amap-picker-popup"
    :show="show"
    position="bottom"
    round
    :lazy-render="false"
    :style="{ height: '85%', width: '100%', maxWidth: '480px', margin: '0 auto' }"
    @update:show="emit('update:show', $event)"
    @opened="onPopupOpened"
  >
    <div class="amap-shell">
    <div class="amap-head">
      <span class="title">{{ panelTitle }}</span>
      <div class="amap-head__actions">
        <van-button size="small" plain type="primary" @click="onClickCurrentLocation">定位到当前</van-button>
        <van-button size="small" @click="onClose">关闭</van-button>
      </div>
    </div>
    <div class="amap-search">
      <van-search
        v-model="searchKeyword"
        placeholder="村名等会在田畈街镇、金盘岭镇优先检索"
        show-action
        @search="onSearchSubmit"
        @cancel="searchKeyword = ''"
      >
        <template #action>
          <div role="button" tabindex="0" class="amap-search__go" @click="onSearchSubmit">搜索</div>
        </template>
      </van-search>
      <div class="amap-subareas" role="group" aria-label="鄱阳县内区域">
        <span class="amap-subareas__label">区域</span>
        <van-button size="mini" plain type="primary" @click="onPoyangSubArea('county')">全县</van-button>
        <van-button size="mini" plain type="primary" @click="onPoyangSubArea('tianfan')">田畈街</van-button>
        <van-button size="mini" plain type="primary" @click="onPoyangSubArea('jinpanling')">金盘岭</van-button>
      </div>
    </div>
    <div v-if="searchHits.length" class="amap-hit-list">
      <div
        v-for="(h, i) in searchHits"
        :key="`${h.lng}-${h.lat}-${i}`"
        class="amap-hit"
        role="button"
        @click="onPickSearchHit(h)"
      >
        <div class="amap-hit__name">
          <span v-if="h.regionHint" class="amap-hit__region">{{ h.regionHint }}</span>
          {{ h.name }}
        </div>
        <div v-if="h.address" class="amap-hit__addr">{{ h.address }}</div>
      </div>
    </div>
    <div v-show="loading" class="amap-loading">加载中…</div>
    <div v-show="positioning && !loading" class="amap-loading amap-loading--sub">正在定位…</div>
    <div ref="mapEl" class="amap-box" />
    <div class="amap-addr">
      {{
        pickedAddress ||
          '默认鄱阳县；村名搜索会同时在田畈街镇、金盘岭镇匹配；可点区域缩小范围或地图上选点，亦可「定位到当前」'
      }}
    </div>
    <div class="amap-actions">
      <van-button
        type="primary"
        block
        round
        :disabled="pickedLng == null || pickedLat == null"
        @click="onConfirm"
      >
        使用该地址
      </van-button>
    </div>
    </div>
  </van-popup>

  <van-dialog
    v-model:show="showLocConsentDialog"
    class="amap-loc-dialog"
    title="获取位置信息"
    show-cancel-button
    :close-on-click-overlay="false"
    confirm-button-text="同意并继续"
    cancel-button-text="暂不定位"
    teleport="body"
    @confirm="onLocConsentConfirm"
    @cancel="onLocConsentCancel"
  >
    <p class="amap-loc-dialog__text">
      为将地图居中到您当前位置附近，需要使用设备的地理位置。随后系统或浏览器可能会请求位置权限，请选择「允许」。
    </p>
  </van-dialog>

  <van-dialog
    v-model:show="showLocFailDialog"
    class="amap-loc-dialog"
    title="定位未成功"
    show-cancel-button
    confirm-button-text="重试定位"
    cancel-button-text="知道了"
    teleport="body"
    @confirm="onLocFailRetry"
    @cancel="onLocFailDismiss"
  >
    <div class="amap-loc-dialog__body">
      <p class="amap-loc-dialog__lead">可依次检查：</p>
      <ul class="amap-loc-dialog__ul">
        <li>手机系统设置中已开启「定位服务 / GPS」</li>
        <li>浏览器或微信内对本站点允许「位置」权限</li>
        <li>使用 HTTPS 访问页面（开发环境可用 localhost）</li>
        <li>在室外或信号较好环境重试</li>
      </ul>
      <p class="amap-loc-dialog__hint">您也可在地图上直接点选，或使用上方搜索。</p>
    </div>
  </van-dialog>
</template>

<style scoped>
.amap-picker-popup {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.amap-picker-popup :deep(.van-popup__content) {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.amap-shell {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
.amap-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--van-border-color);
  flex-shrink: 0;
}
.title {
  font-weight: 600;
}
.amap-head__actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.amap-search {
  flex-shrink: 0;
  border-bottom: 1px solid var(--van-border-color);
}
.amap-subareas {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 0 16px 10px;
  font-size: 12px;
  color: var(--van-text-color-2);
}
.amap-subareas__label {
  flex-shrink: 0;
  margin-right: 2px;
}
.amap-search :deep(.van-search__content) {
  background: var(--van-background, #f7f8fa);
}
.amap-search__go {
  padding: 0 4px;
  font-size: 14px;
  color: var(--van-primary-color, #1989fa);
  cursor: pointer;
}
.amap-hit-list {
  max-height: 140px;
  overflow: auto;
  border-bottom: 1px solid var(--van-border-color);
  background: var(--van-background-2, #fff);
  flex-shrink: 0;
}
.amap-hit {
  padding: 10px 16px;
  text-align: left;
  border-bottom: 1px solid var(--van-border-color);
  cursor: pointer;
}
.amap-hit:last-child {
  border-bottom: none;
}
.amap-hit:active {
  background: var(--van-active-color, rgba(0, 0, 0, 0.05));
}
.amap-hit__name {
  font-size: 14px;
  font-weight: 500;
  color: var(--van-text-color);
}
.amap-hit__region {
  display: inline-block;
  margin-right: 6px;
  padding: 0 5px;
  font-size: 11px;
  font-weight: 500;
  color: var(--van-primary-color, #1989fa);
  vertical-align: middle;
  border: 1px solid var(--van-primary-color, #1989fa);
  border-radius: 3px;
  line-height: 1.3;
}
.amap-hit__addr {
  margin-top: 4px;
  font-size: 12px;
  color: var(--van-text-color-2);
  line-height: 1.3;
}
.amap-box {
  width: 100%;
  flex-shrink: 0;
  /* flex:1 在多层嵌套下高度常为 0，高德无法绘制瓦片 → 白屏 */
  height: 45vh;
  min-height: 260px;
  max-height: 52vh;
  position: relative;
  background: #e8e8e8;
}
.amap-loading {
  padding: 8px 12px;
  text-align: center;
  font-size: 13px;
  color: var(--van-text-color-2);
}
.amap-loading--sub {
  padding-top: 0;
}
.amap-addr {
  padding: 10px 16px;
  font-size: 13px;
  color: var(--van-text-color);
  line-height: 1.4;
  max-height: 72px;
  overflow: auto;
  flex-shrink: 0;
}
.amap-actions {
  padding: 12px 16px max(12px, env(safe-area-inset-bottom));
  flex-shrink: 0;
}

.amap-loc-dialog__text,
.amap-loc-dialog__body {
  margin: 0;
  padding: 8px 4px 4px;
  font-size: 14px;
  line-height: 1.55;
  color: var(--van-text-color, #323233);
  text-align: left;
}
.amap-loc-dialog__lead {
  margin: 0 0 6px;
  font-weight: 500;
}
.amap-loc-dialog__ul {
  margin: 0 0 10px;
  padding-left: 1.1em;
}
.amap-loc-dialog__ul li {
  margin-bottom: 4px;
}
.amap-loc-dialog__hint {
  margin: 0;
  font-size: 13px;
  color: var(--van-text-color-2, #646566);
}
</style>
