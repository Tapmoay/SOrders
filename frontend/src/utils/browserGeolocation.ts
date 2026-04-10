/**
 * 浏览器 HTML5 Geolocation（WGS84）。
 * 国内高德/腾讯地图需再转 GCJ-02（如 AMap.convertFrom）。
 */

export type BrowserGeoCoords = {
  latitude: number
  longitude: number
  /** 米；部分环境可能为 null */
  accuracy: number | null
  /** 浏览器返回为 WGS84 */
  source: 'wgs84'
}

export type BrowserGeoErrorCode =
  | 'unsupported'
  | 'permission_denied'
  | 'position_unavailable'
  | 'timeout'
  | 'unknown'

export type BrowserGeoResult =
  | { ok: true; coords: BrowserGeoCoords }
  | { ok: false; code: BrowserGeoErrorCode; message: string }

const defaultOptions: PositionOptions = {
  enableHighAccuracy: true,
  timeout: 20000,
  maximumAge: 0,
}

function mapErrorCode(code: number): BrowserGeoErrorCode {
  switch (code) {
    case 1:
      return 'permission_denied'
    case 2:
      return 'position_unavailable'
    case 3:
      return 'timeout'
    default:
      return 'unknown'
  }
}

/**
 * 尝试通过浏览器获取当前一次定位（需 HTTPS，localhost 除外；需用户授权）。
 */
export function tryGetBrowserGeolocation(options?: PositionOptions): Promise<BrowserGeoResult> {
  if (typeof navigator === 'undefined' || !navigator.geolocation) {
    return Promise.resolve({
      ok: false,
      code: 'unsupported',
      message: '当前环境不支持地理定位',
    })
  }

  const opts = { ...defaultOptions, ...options }

  return new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        resolve({
          ok: true,
          coords: {
            latitude: pos.coords.latitude,
            longitude: pos.coords.longitude,
            accuracy: Number.isFinite(pos.coords.accuracy) ? pos.coords.accuracy : null,
            source: 'wgs84',
          },
        })
      },
      (err) => {
        resolve({
          ok: false,
          code: mapErrorCode(err.code),
          message: err.message || '获取定位失败',
        })
      },
      opts,
    )
  })
}
