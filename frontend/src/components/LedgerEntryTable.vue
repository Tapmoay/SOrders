<script setup lang="ts">
import { computed, ref } from 'vue'

import type { LedgerEntry } from '@/api/ledger'
import OrderDetailPopup from '@/components/OrderDetailPopup.vue'
import { formatMoney2 } from '@/utils/formatMoney'

const props = defineProps<{
  entries: LedgerEntry[]
  readOnly: boolean
  orderRouteName: 'shipper-order-detail' | 'dispatcher-order-detail'
}>()

const viewerRole = computed<'shipper' | 'dispatcher'>(() =>
  props.orderRouteName === 'shipper-order-detail' ? 'shipper' : 'dispatcher',
)

const orderPopupShow = ref(false)
const orderPopupId = ref<number | null>(null)

function openOrderDetail(row: LedgerEntry) {
  if (!row.order_id) return
  orderPopupId.value = row.order_id
  orderPopupShow.value = true
}

/** 入账具体时间：优先账本记录创建时间，否则回退到业务日期 */
function formatEntryDateTime(row: LedgerEntry): string {
  const iso = row.created_at
  if (iso) {
    const d = new Date(iso)
    if (!Number.isNaN(d.getTime())) {
      const p = (n: number) => String(n).padStart(2, '0')
      return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
    }
  }
  return row.entry_date || '—'
}

const emit = defineEmits<{
  edit: [row: LedgerEntry]
  delete: [row: LedgerEntry]
}>()
</script>

<template>
  <div class="ledger-table-wrap">
    <table class="ledger-table">
      <thead>
        <tr>
          <th>具体时间</th>
          <th>商品名称</th>
          <th class="num">数量</th>
          <th class="num">单价</th>
          <th class="num">总价</th>
          <th>订单号</th>
          <th>备注</th>
          <th v-if="!readOnly" class="actions">操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in entries" :key="row.id">
          <td class="cell-time">{{ formatEntryDateTime(row) }}</td>
          <td class="cell-product">{{ row.product_name }}</td>
          <td class="num">{{ row.quantity }}</td>
          <td class="num">{{ formatMoney2(row.unit_price) }}</td>
          <td class="num">{{ formatMoney2(row.total) }}</td>
          <td class="cell-order">
            <button
              v-if="row.order_id"
              type="button"
              class="ledger-order-link"
              @click="openOrderDetail(row)"
            >
              {{ row.order_no || `#${row.order_id}` }}
            </button>
            <span v-else>—</span>
          </td>
          <td class="cell-muted cell-note" :title="row.note || ''">{{ row.note || '—' }}</td>
          <td v-if="!readOnly" class="actions">
            <van-button size="mini" type="primary" plain round @click="emit('edit', row)">编辑</van-button>
            <van-button size="mini" type="danger" plain round @click="emit('delete', row)">删除</van-button>
          </td>
        </tr>
      </tbody>
    </table>

    <OrderDetailPopup
      v-model:show="orderPopupShow"
      :order-id="orderPopupId"
      :viewer-role="viewerRole"
    />
  </div>
</template>

<style scoped>
.ledger-table-wrap {
  margin: 0 12px;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  border-radius: 8px;
  border: 1px solid var(--van-border-color);
  background: var(--van-background-2, #fff);
}

.ledger-table {
  width: 100%;
  min-width: 640px;
  border-collapse: collapse;
  font-size: 13px;
}

.ledger-table th,
.ledger-table td {
  padding: 10px 8px;
  border-bottom: 1px solid var(--van-border-color);
  vertical-align: top;
}

.ledger-table th {
  font-weight: 600;
  color: var(--van-text-color-2);
  background: var(--van-background, #f7f8fa);
  white-space: nowrap;
}

.ledger-table tr:last-child td {
  border-bottom: none;
}

.num {
  text-align: right;
  white-space: nowrap;
}

.cell-time {
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.cell-product {
  max-width: 160px;
  word-break: break-word;
}

.cell-muted {
  max-width: 120px;
  color: var(--van-text-color-2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cell-note {
  max-width: 100px;
}

.cell-order {
  white-space: nowrap;
}

.ledger-order-link {
  padding: 0;
  border: none;
  background: none;
  font: inherit;
  cursor: pointer;
  color: var(--van-primary-color, #1677ff);
  text-decoration: underline;
  font-weight: 500;
}

.ledger-order-link:active {
  opacity: 0.75;
}

.actions {
  white-space: nowrap;
}

.actions :deep(.van-button) {
  margin-right: 4px;
  margin-bottom: 4px;
}
</style>
