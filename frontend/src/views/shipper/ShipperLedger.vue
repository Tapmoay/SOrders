<script setup lang="ts">
import { showConfirmDialog, showFailToast, showSuccessToast } from 'vant'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'

import { shipperOrdersRefreshTick } from '@/shipperRealtimeState'

import LedgerEntryTable from '@/components/LedgerEntryTable.vue'
import { createLedgerExportJob, downloadLedgerExportFile, fetchLedgerEntries, getLedgerExportJob, type ExportFormat, type LedgerEntry } from '@/api/ledger'
import { useAuthStore } from '@/stores/auth'
import { formatMoney2 } from '@/utils/formatMoney'

const auth = useAuthStore()
const dateFrom = ref('')
const dateTo = ref('')
const list = ref<LedgerEntry[]>([])
const loading = ref(false)
const exportFmt = ref<ExportFormat>('excel')
const exporting = ref(false)
let pollTimer: ReturnType<typeof setInterval> | null = null

const stats = computed(() => {
  let sum = 0
  for (const r of list.value) {
    const t = Number(r.total)
    if (!Number.isNaN(t)) sum += t
  }
  return { count: list.value.length, sum }
})

async function load() {
  loading.value = true
  try {
    list.value = await fetchLedgerEntries({
      date_from: dateFrom.value || undefined,
      date_to: dateTo.value || undefined,
    })
  } catch {
    showFailToast('加载失败')
  } finally {
    loading.value = false
  }
}

watch([dateFrom, dateTo], () => {
  void load()
})
watch(shipperOrdersRefreshTick, () => {
  void load()
})

onMounted(() => {
  void load()
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})

async function runExport() {
  const sid = auth.userId
  if (!sid || !dateFrom.value || !dateTo.value) {
    showFailToast('请填写导出日期范围')
    return
  }
  try {
    await showConfirmDialog({ title: '导出账本', message: '将异步生成文件，完成后在消息中心查看下载链接。' })
  } catch {
    return
  }
  exporting.value = true
  try {
    const job = await createLedgerExportJob({
      shipper_id: sid,
      date_from: dateFrom.value,
      date_to: dateTo.value,
      export_format: exportFmt.value,
    })
    showSuccessToast('任务已提交')
    let n = 0
    pollTimer = setInterval(async () => {
      n += 1
      if (n > 60) {
        if (pollTimer) clearInterval(pollTimer)
        pollTimer = null
        exporting.value = false
        return
      }
      try {
        const j = await getLedgerExportJob(job.id)
        if (j.status === 'done' && j.file_path) {
          if (pollTimer) clearInterval(pollTimer)
          pollTimer = null
          exporting.value = false
          // ⚠️ 必须**带 token 以 blob 取回**：`j.file_path` 是产物文件名（不是 URL），
          //    拼成链接是 404；就算拼对了，window.open 也带不上 Authorization 头 → 401，
          //    而界面照样弹「导出完成」= 用户以为导出成功、其实什么都没有。
          try {
            await downloadLedgerExportFile(job)
            showSuccessToast('导出完成，已开始下载')
          } catch (e: unknown) {
            const err = e as { response?: { data?: { detail?: string } } }
            showFailToast(err.response?.data?.detail || '下载失败（文件可能已被清理）')
          }
        } else if (j.status === 'failed') {
          if (pollTimer) clearInterval(pollTimer)
          pollTimer = null
          exporting.value = false
          showFailToast(j.error_message || '失败')
        }
      } catch {
        /* ignore */
      }
    }, 2000)
  } catch {
    showFailToast('提交失败')
    exporting.value = false
  }
}
</script>

<template>
  <div class="s-ledger">
    <van-notice-bar
      wrapable
      :scrollable="false"
      left-icon="info-o"
      text="账本为订单送达后按明细自动入账；仅显示已绑定到您账号的订单。若订单仅有「临时货主称呼」未绑定账号，入账在派单员端临时名下，此处不显示。与派单员端一致；仅派单员可编辑。点击订单号可查看订单。"
    />
    <van-cell-group inset title="筛选" class="s-ledger__filter">
      <van-field v-model="dateFrom" label="开始日期" placeholder="留空=不限制" />
      <van-field v-model="dateTo" label="结束日期" placeholder="留空=不限制" />
    </van-cell-group>

    <div class="bar">
      <van-button size="small" @click="load">刷新</van-button>
      <van-radio-group v-model="exportFmt" direction="horizontal" class="fmt">
        <van-radio name="excel">Excel</van-radio>
        <van-radio name="pdf">PDF</van-radio>
      </van-radio-group>
      <van-button size="small" type="primary" :loading="exporting" @click="runExport">导出</van-button>
    </div>

    <van-loading v-if="loading" vertical class="s-ledger__loading">加载中…</van-loading>
    <template v-else>
      <van-cell-group v-if="list.length" inset title="汇总（当前筛选）" class="s-ledger__stats">
        <van-cell title="记录条数" :value="String(stats.count)" />
        <van-cell title="金额合计（元）" :value="formatMoney2(stats.sum)" />
      </van-cell-group>
      <van-empty v-if="!list.length" description="暂无记录" />
      <LedgerEntryTable
        v-else
        :entries="list"
        read-only
        order-route-name="shipper-order-detail"
      />
    </template>
  </div>
</template>

<style scoped>
.s-ledger {
  padding-bottom: 24px;
}

.s-ledger__filter {
  margin-top: 8px;
}

.s-ledger__stats {
  margin: 0 0 12px;
}

.s-ledger__stats :deep(.van-cell__value) {
  font-weight: 600;
  color: var(--van-primary-color, #1677ff);
}

.s-ledger__loading {
  padding: 48px 0;
}

.bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
}
.fmt {
  flex: 1;
  min-width: 140px;
}
</style>
