/**
 * Open Amap navigation (H5 universal URI). Falls back to web if app scheme fails.
 * @param lng GCJ-02 longitude
 * @param lat GCJ-02 latitude
 */
export function openAmapNavigation(lng: number, lat: number, name: string): void {
  const n = encodeURIComponent(name || '目的地')
  const web = `https://uri.amap.com/navigation?to=${lng},${lat},${n}&mode=car&policy=1&src=mypage&coordinate=gaode&callnative=1`
  const ua = navigator.userAgent || ''
  const isAndroid = /Android/i.test(ua)
  const isIOS = /iPhone|iPad|iPod/i.test(ua)
  if (isAndroid) {
    const scheme = `androidamap://route?sourceApplication=sorders&dev=0&t=0&dlat=${lat}&dlon=${lng}&dname=${n}&style=0`
    window.location.href = scheme
    window.setTimeout(() => {
      window.open(web, '_blank', 'noopener,noreferrer')
    }, 600)
    return
  }
  if (isIOS) {
    const scheme = `iosamap://path?sourceApplication=sorders&dlat=${lat}&dlon=${lng}&dname=${n}&dev=0&t=0`
    window.location.href = scheme
    window.setTimeout(() => {
      window.open(web, '_blank', 'noopener,noreferrer')
    }, 600)
    return
  }
  window.open(web, '_blank', 'noopener,noreferrer')
}
