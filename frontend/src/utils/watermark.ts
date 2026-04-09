/** 送达照片水印文案：时间 + 地址（或 GPS 描述） */
export function buildDeliveryWatermarkLines(addressOrGpsLine: string): string[] {
  const t = formatWatermarkTime()
  const loc = (addressOrGpsLine || '').trim()
  if (!loc) return [t]
  const line2 = loc.length > 120 ? `${loc.slice(0, 120)}…` : loc
  return [t, line2]
}

/** Draw time + location lines on bottom-left of image; output JPEG blob. */
export async function addWatermarkToBlob(
  blob: Blob,
  lines: string[],
  quality = 0.92,
): Promise<Blob> {
  const bmp = await createImageBitmap(blob)
  const canvas = document.createElement('canvas')
  canvas.width = bmp.width
  canvas.height = bmp.height
  const ctx = canvas.getContext('2d')
  if (!ctx) return blob
  ctx.drawImage(bmp, 0, 0)
  const fontPx = Math.max(14, Math.floor(bmp.width / 38))
  ctx.font = `${fontPx}px system-ui, sans-serif`
  const lh = fontPx * 1.35
  const pad = Math.max(10, Math.floor(fontPx * 0.6))
  const filtered = lines.map((s) => s.trim()).filter(Boolean)
  ctx.textBaseline = 'bottom'
  for (let i = 0; i < filtered.length; i++) {
    const line = filtered[filtered.length - 1 - i]!
    const y = bmp.height - pad - i * lh
    ctx.strokeStyle = 'rgba(255,255,255,0.85)'
    ctx.lineWidth = 3
    ctx.strokeText(line, pad, y)
    ctx.fillStyle = 'rgba(0,0,0,0.78)'
    ctx.fillText(line, pad, y)
  }
  return new Promise((resolve) => {
    canvas.toBlob((b) => resolve(b ?? blob), 'image/jpeg', quality)
  })
}

export function formatWatermarkTime(d = new Date()): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}
