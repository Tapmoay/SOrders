import { http } from './client'

export type ChartGranularity = 'month' | 'year'
export type ChartMetric = 'quantity' | 'amount'

export interface ShipperProductChart {
  granularity: ChartGranularity
  metric: ChartMetric
  categories: string[]
  series: { name: string; data: number[] }[]
}

export interface TopProductItem {
  product_name: string
  count: number
  amount: string | number
}

export interface ShipperActivity {
  shipper_id: number
  shipper_name: string
  order_count: number
  delivered_count: number
  total_spent: string | number
  avg_order_value: string | number
  orders_per_week: string | number
  top_products: TopProductItem[]
}

export interface DrilldownOrderItem {
  id: number
  order_no: string
  order_date: string
  status: string
  shipper_name: string | null
  product_name: string
  quantity: number
  line_total: string | number
}

export interface DriverPerformanceRow {
  driver_id: number
  driver_name: string
  completed_count: number
  on_time_rate: number | null
  avg_delivery_seconds: number | null
  photo_upload_rate: number
}

export interface DriverPerformance {
  period_label: string
  drivers: DriverPerformanceRow[]
}

export interface ExceptionOrderItem {
  id: number
  order_no: string
  order_date: string
  status: string
  shipper_name: string | null
  driver_name: string | null
  exception_reason: string
  exception_resolution: string
  expected_deliver_before: string | null
  delivered_at: string | null
}

export interface StatsExportBody {
  date_from: string
  date_to: string
  include_shipper_chart?: boolean
  include_driver_perf?: boolean
  include_exceptions?: boolean
  chart_metric?: ChartMetric
  chart_granularity?: ChartGranularity
}

export async function fetchShipperProductChart(params: {
  date_from: string
  date_to: string
  granularity: ChartGranularity
  metric: ChartMetric
}) {
  const { data } = await http.get<ShipperProductChart>('/stats/shipper-product-chart', { params })
  return data
}

export async function fetchShipperActivity(params: {
  shipper_id: number
  date_from: string
  date_to: string
}) {
  const { data } = await http.get<ShipperActivity>('/stats/shipper-activity', { params })
  return data
}

export async function fetchProductDrilldown(params: {
  product_name: string
  date_from: string
  date_to: string
}) {
  const { data } = await http.get<DrilldownOrderItem[]>('/stats/product-drilldown', { params })
  return data
}

export async function fetchDriverPerformance(params: { date_from: string; date_to: string }) {
  const { data } = await http.get<DriverPerformance>('/stats/driver-performance', { params })
  return data
}

export async function fetchExceptionOrders(params: { date_from: string; date_to: string }) {
  const { data } = await http.get<ExceptionOrderItem[]>('/stats/exception-orders', { params })
  return data
}

export async function downloadStatsExport(body: StatsExportBody) {
  const res = await http.post('/stats/export', body, { responseType: 'blob' })
  const blob = res.data as Blob
  const cd = res.headers['content-disposition'] as string | undefined
  let name = `stats-${body.date_from}-${body.date_to}.xlsx`
  if (cd) {
    const m = /filename="?([^";]+)"?/i.exec(cd)
    if (m?.[1]) name = m[1]
  }
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  URL.revokeObjectURL(url)
}
