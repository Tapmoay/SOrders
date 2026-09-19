<script setup lang="ts">
import * as echarts from 'echarts'
import { showFailToast, showToast } from 'vant'
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'

import {
  downloadStatsExport,
  fetchDriverPerformance,
  fetchExceptionOrders,
  fetchProductDrilldown,
  fetchShipperActivity,
  fetchShipperProductChart,
  type ChartGranularity,
  type ChartMetric,
  type DrilldownOrderItem,
  type DriverPerformance,
  type ExceptionOrderItem,
  type ShipperActivity,
  type ShipperProductChart,
} from '@/api/stats'
import { fetchUsers, type UserListItem } from '@/api/user'
import { formatApiError } from '@/utils/apiError'
import { ORDER_STATUS_LABEL } from '@/constants/order'
import type { OrderStatus } from '@/types/order'
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

const dateFrom = ref(firstDayOfMonthStr())
const dateTo = ref(todayStr())
const mainTab = ref(0)

const granularity = ref<ChartGranularity>('month')
const metric = ref<ChartMetric>('quantity')
const chartLoading = ref(false)
const chartData = ref<ShipperProductChart | null>(null)
const chartEl = ref<HTMLDivElement | null>(null)
let chartInst: echarts.ECharts | null = null

const shippers = ref<UserListItem[]>([])
const pickShipper = ref(false)
const shipperId = ref<number | null>(null)
const activity = ref<ShipperActivity | null>(null)
const actLoading = ref(false)

const drillOpen = ref(false)
const drillName = ref('')
const drillRows = ref<DrilldownOrderItem[]>([])
const drillLoading = ref(false)

const driverData = ref<DriverPerformance | null>(null)
const driverLoading = ref(false)

const exceptions = ref<ExceptionOrderItem[]>([])
const exLoading = ref(false)

const exporting = ref(false)

const shipperLabel = computed(() => {
  if (!shipperId.value) return ''
  const s = shippers.value.find((x) => x.id === shipperId.value)
  return s ? `${s.full_name || s.phone}` : ''
})

function fmtSec(s: number | null | undefined) {
  if (s == null || Number.isNaN(s)) return '—'
  const m = Math.floor(s / 60)
  const sec = Math.round(s % 60)
  return m > 0 ? `${m}分${sec}秒` : `${sec}秒`
}

function pct(x: number | null | undefined) {
  if (x == null || Number.isNaN(x)) return '—'
  return `${(x * 100).toFixed(1)}%`
}

function resizeChart() {
  chartInst?.resize()
}

async function loadShippers() {
  try {
    shippers.value = await fetchUsers({ role: 'shipper' })
  } catch (e: unknown) {
    showFailToast(formatApiError(e, '加载货主失败'))
  }
}

function buildChartOption(data: ShipperProductChart): echarts.EChartsOption {
  const categories = data.categories ?? []
  const rawSeries = data.series ?? []
  const series = rawSeries.map((s) => ({
    name: s.name,
    type: 'bar' as const,
    emphasis: { focus: 'series' as const },
    data: Array.isArray(s.data) ? s.data : [],
  }))
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: {
      type: 'scroll',
      bottom: 0,
      data: rawSeries.map((s) => s.name),
    },
    grid: { left: '3%', right: '4%', bottom: '18%', top: '8%', containLabel: true },
    xAxis: {
      type: 'category',
      data: categories,
      axisLabel: { rotate: categories.length > 6 ? 30 : 0 },
    },
    yAxis: { type: 'value', scale: true },
    series,
  }
}

async function loadChart() {
  if (!dateFrom.value || !dateTo.value) return
  chartLoading.value = true
  chartData.value = null
  try {
    chartData.value = await fetchShipperProductChart({
      date_from: dateFrom.value,
      date_to: dateTo.value,
      granularity: granularity.value,
      metric: metric.value,
    })
  } catch (e: unknown) {
    chartData.value = null
    showFailToast(formatApiError(e, '图表加载失败'))
    return
  } finally {
    chartLoading.value = false
  }

  // 须在容器可见后再 init/setOption，否则宽高为 0 时 ECharts 可能抛错
  await nextTick()
  await nextTick()
  if (!chartEl.value) return

  const categories = chartData.value?.categories ?? []
  const seriesList = chartData.value?.series ?? []
  const hasData = categories.length > 0 && seriesList.length > 0

  try {
    if (!chartInst) chartInst = echarts.init(chartEl.value)
    if (!hasData) {
      chartInst.clear()
      return
    }
    const opt = buildChartOption({
      ...chartData.value!,
      categories,
      series: seriesList,
    })
    chartInst.setOption(opt, true)
    chartInst.resize()
    chartInst.off('click')
    chartInst.on('click', (p) => {
      if (p.componentType === 'series' && typeof p.seriesName === 'string') {
        void openDrilldown(p.seriesName)
      }
    })
  } catch (e: unknown) {
    console.error(e)
    showFailToast(formatApiError(e, '图表渲染失败'))
  }
}

async function loadActivity() {
  if (!shipperId.value || !dateFrom.value || !dateTo.value) {
    activity.value = null
    return
  }
  actLoading.value = true
  try {
    activity.value = await fetchShipperActivity({
      shipper_id: shipperId.value,
      date_from: dateFrom.value,
      date_to: dateTo.value,
    })
  } catch {
    showFailToast('活跃度加载失败')
    activity.value = null
  } finally {
    actLoading.value = false
  }
}

async function openDrilldown(productName: string) {
  if (!dateFrom.value || !dateTo.value) return
  drillName.value = productName
  drillOpen.value = true
  drillLoading.value = true
  drillRows.value = []
  try {
    drillRows.value = await fetchProductDrilldown({
      product_name: productName,
      date_from: dateFrom.value,
      date_to: dateTo.value,
    })
  } catch {
    showFailToast('明细加载失败')
  } finally {
    drillLoading.value = false
  }
}

async function loadDriver() {
  if (!dateFrom.value || !dateTo.value) return
  driverLoading.value = true
  try {
    driverData.value = await fetchDriverPerformance({
      date_from: dateFrom.value,
      date_to: dateTo.value,
    })
  } catch {
    showFailToast('司机绩效加载失败')
    driverData.value = null
  } finally {
    driverLoading.value = false
  }
}

async function loadExceptions() {
  if (!dateFrom.value || !dateTo.value) return
  exLoading.value = true
  try {
    exceptions.value = await fetchExceptionOrders({
      date_from: dateFrom.value,
      date_to: dateTo.value,
    })
  } catch {
    showFailToast('异常订单加载失败')
    exceptions.value = []
  } finally {
    exLoading.value = false
  }
}

function presetRange(mode: 'day' | 'month' | 'year') {
  const now = new Date()
  const t = todayStr()
  if (mode === 'day') {
    dateFrom.value = t
    dateTo.value = t
  } else if (mode === 'month') {
    dateFrom.value = firstDayOfMonthStr()
    dateTo.value = t
  } else {
    dateFrom.value = `${now.getFullYear()}-01-01`
    dateTo.value = t
  }
  showToast(`已切换为${mode === 'day' ? '今日' : mode === 'month' ? '本月' : '本年'}范围`)
  void refreshCurrentTab()
}

async function refreshCurrentTab() {
  if (mainTab.value === 0) {
    await loadChart()
    await loadActivity()
  } else if (mainTab.value === 1) await loadDriver()
  else await loadExceptions()
}

async function runExport() {
  if (!dateFrom.value || !dateTo.value) {
    showFailToast('请填写日期范围')
    return
  }
  exporting.value = true
  try {
    await downloadStatsExport({
      date_from: dateFrom.value,
      date_to: dateTo.value,
      include_shipper_chart: true,
      include_driver_perf: true,
      include_exceptions: true,
      chart_metric: metric.value,
      chart_granularity: granularity.value,
    })
    showToast('已开始下载')
  } catch {
    showFailToast('导出失败')
  } finally {
    exporting.value = false
  }
}

watch([granularity, metric], () => {
  if (mainTab.value === 0) void loadChart()
})

watch([shipperId, dateFrom, dateTo], () => {
  if (mainTab.value === 0) void loadActivity()
})

watch(mainTab, (t) => {
  if (t === 0) {
    void loadChart()
    void loadActivity()
  } else if (t === 1) void loadDriver()
  else void loadExceptions()
})

watch([dateFrom, dateTo], () => {
  void refreshCurrentTab()
})

onMounted(async () => {
  await loadShippers()
  window.addEventListener('resize', resizeChart)
  await loadChart()
  await loadActivity()
})

onUnmounted(() => {
  window.removeEventListener('resize', resizeChart)
  chartInst?.dispose()
  chartInst = null
})
</script>

<template>
  <div class="dash role-tool-page">
    <van-notice-bar
      left-icon="info-o"
      text="统计基于已送达订单（商品柱状图）；司机绩效按送达时间筛选。点击柱状系列可下钻订单行。"
    />

    <van-field v-model="dateFrom" label="开始" placeholder="YYYY-MM-DD" />
    <van-field v-model="dateTo" label="结束" placeholder="YYYY-MM-DD" />

    <div class="bar-row">
      <van-button size="small" @click="presetRange('day')">今日</van-button>
      <van-button size="small" @click="presetRange('month')">本月</van-button>
      <van-button size="small" @click="presetRange('year')">本年</van-button>
      <van-button size="small" type="primary" :loading="exporting" @click="runExport">导出 Excel</van-button>
    </div>

    <van-tabs v-model:active="mainTab" shrink>
      <van-tab title="货主" />
      <van-tab title="司机" />
      <van-tab title="异常" />
    </van-tabs>

    <div v-show="mainTab === 0" class="panel">
      <div class="subbar">
        <span class="lbl">粒度</span>
        <van-radio-group v-model="granularity" direction="horizontal">
          <van-radio name="month">月</van-radio>
          <van-radio name="year">年</van-radio>
        </van-radio-group>
      </div>
      <div class="subbar">
        <span class="lbl">指标</span>
        <van-radio-group v-model="metric" direction="horizontal">
          <van-radio name="quantity">数量</van-radio>
          <van-radio name="amount">金额</van-radio>
        </van-radio-group>
      </div>

      <van-loading v-if="chartLoading" vertical>加载图表</van-loading>
      <div v-show="!chartLoading" ref="chartEl" class="chart-box" />

      <van-field label="货主活跃度" readonly is-link :model-value="shipperLabel" placeholder="选择货主" @click="pickShipper = true" />
      <van-loading v-if="actLoading" vertical>加载活跃度</van-loading>
      <van-cell-group v-else-if="activity" inset class="act">
        <van-cell title="下单次数" :value="String(activity.order_count)" />
        <van-cell title="已送达" :value="String(activity.delivered_count)" />
        <van-cell title="总消费" :value="`¥${formatMoney2(activity.total_spent)}`" />
        <van-cell title="客单价(已送达)" :value="`¥${formatMoney2(activity.avg_order_value)}`" />
        <van-cell title="约每周下单" :value="formatMoney2(activity.orders_per_week)" />
        <van-cell title="常用商品" :label="activity.top_products.map((p) => p.product_name).join('、') || '—'" />
      </van-cell-group>
      <van-empty v-else description="请选择货主查看活跃度" />
    </div>

    <div v-show="mainTab === 1" class="panel">
      <van-loading v-if="driverLoading" vertical>加载司机绩效</van-loading>
      <template v-else-if="driverData">
        <div class="hint">{{ driverData.period_label }} · 按送达时间</div>
        <van-cell-group v-for="row in driverData.drivers" :key="row.driver_id" inset class="drv">
          <van-cell :title="row.driver_name" :value="`完成 ${row.completed_count} 单`" />
          <van-cell title="准时率" :value="pct(row.on_time_rate)" />
          <van-cell title="平均送达时长" :value="fmtSec(row.avg_delivery_seconds)" />
          <van-cell title="照片上传率" :value="pct(row.photo_upload_rate)" />
        </van-cell-group>
        <van-empty v-if="!driverData.drivers.length" description="暂无数据" />
      </template>
    </div>

    <div v-show="mainTab === 2" class="panel">
      <van-loading v-if="exLoading" vertical>加载异常</van-loading>
      <template v-else>
        <van-cell-group v-for="ex in exceptions" :key="ex.id" inset class="ex">
          <van-cell :title="ex.order_no" :value="ex.order_date" />
          <!-- 后端给的是状态码（DELIVERED…），直接印上去用户看不懂 -->
          <van-cell title="状态" :value="ORDER_STATUS_LABEL[ex.status as OrderStatus] || ex.status" />
          <van-cell title="货主" :value="ex.shipper_name || '—'" />
          <van-cell title="司机" :value="ex.driver_name || '—'" />
          <van-cell title="原因" :label="ex.exception_reason || '—'" />
          <van-cell title="处理" :label="ex.exception_resolution || '—'" />
        </van-cell-group>
        <van-empty v-if="!exceptions.length" description="暂无异常订单" />
      </template>
    </div>

    <van-popup v-model:show="pickShipper" position="bottom" round>
      <van-nav-bar title="货主" left-text="关闭" @click-left="pickShipper = false" />
      <van-cell
        v-for="s in shippers"
        :key="s.id"
        :title="s.full_name || s.phone"
        @click=";(shipperId = s.id), (pickShipper = false)"
      />
    </van-popup>

    <van-popup v-model:show="drillOpen" position="bottom" round :style="{ height: '70%' }">
      <van-nav-bar :title="`明细 · ${drillName}`" left-text="关闭" @click-left="drillOpen = false" />
      <van-loading v-if="drillLoading" vertical>加载</van-loading>
      <van-cell-group v-else v-for="r in drillRows" :key="`${r.id}-${r.product_name}`" inset>
        <van-cell :title="r.order_no" :value="r.order_date" />
        <van-cell title="货主" :value="r.shipper_name || '—'" />
        <van-cell title="数量 / 行金额" :value="`${r.quantity} / ¥${formatMoney2(r.line_total)}`" />
      </van-cell-group>
      <van-empty v-if="!drillLoading && !drillRows.length" description="无匹配行" />
    </van-popup>
  </div>
</template>

<style scoped>
.dash {
  padding-bottom: 16px;
}
.bar-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 8px 12px;
  align-items: center;
}
.subbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 4px 12px;
}
.lbl {
  font-size: 13px;
  color: #646566;
  min-width: 36px;
}
.chart-box {
  width: 100%;
  height: 320px;
}
.panel {
  min-height: 120px;
}
.hint {
  font-size: 12px;
  color: #969799;
  padding: 8px 16px;
}
.act,
.drv,
.ex {
  margin-top: 8px;
}
</style>
