<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { showConfirmDialog, showFailToast, showImagePreview } from 'vant'

import { cancelOrder, deleteCancelledOrder } from '@/api/orders'
import { CANCELLABLE_STATUSES, ORDER_STATUS_LABEL, orderStatusTagType } from '@/constants/order'
import type { Order } from '@/types/order'
import { formatMoney2 } from '@/utils/formatMoney'

const props = defineProps<{
  order: Order
  /** 当前查看者身份，控制可见字段与撤销入口；司机仅浏览 */
  viewerRole: 'shipper' | 'dispatcher' | 'driver'
}>()

const emit = defineEmits<{
  reload: []
}>()

const router = useRouter()

const isShipper = computed(() => props.viewerRole === 'shipper')
const isDispatcher = computed(() => props.viewerRole === 'dispatcher')
const isDriver = computed(() => props.viewerRole === 'driver')

const photoUrls = computed(() => {
  const u = props.order.delivery_photo_urls
  if (!u || !Array.isArray(u)) return [] as string[]
  return u.filter((x): x is string => typeof x === 'string')
})

const watermarkText = computed(() => {
  const o = props.order
  const t = o.delivered_at ? new Date(o.delivered_at).toLocaleString('zh-CN') : ''
  const addr = o.address_detail || ''
  return [t, addr].filter(Boolean).join(' · ')
})

function previewPhotos(urls: string[], start: number) {
  showImagePreview({ images: urls, startPosition: start })
}

function call(phone: string) {
  window.location.href = `tel:${phone}`
}

function emptyText(v: string | null | undefined, placeholder = '未填写') {
  const t = (v ?? '').trim()
  return t ? t : placeholder
}

async function tryCancel() {
  const o = props.order
  // 与列表页同一处判据（真源=后端 `cancel_pending` 的状态门）：待派单 + 已派单（司机未接）。
  if (!CANCELLABLE_STATUSES.includes(o.status)) return
  const note = o.status === 'DISPATCHED' ? '该单已派给司机（还没接单），撤销后司机会收到通知。' : ''
  try {
    await showConfirmDialog({ title: '撤销订单', message: `确定撤销该订单？${note}` })
    await cancelOrder(o.id)
    emit('reload')
  } catch (e) {
    if (e !== 'cancel') {
      const err = e as { response?: { data?: { detail?: string } } }
      showFailToast(err.response?.data?.detail || '撤销失败')
    }
  }
}

async function tryDeleteCancelled() {
  const o = props.order
  if (o.status !== 'CANCELLED' || (!isShipper.value && !isDispatcher.value)) return
  try {
    await showConfirmDialog({
      title: '删除订单',
      // ⛔ 这句原来写的是「删除后不可恢复」，与后端**相反**：`DELETE /orders/{id}` 是**软删除**
      //    （进隔离区 30 天，用户看不见、派单员可查可恢复，到期才物理清理 —— 见
      //    `orders.py::delete_cancelled_order` 与 `services/data_retention.py`）。
      //    按"不可恢复"说，用户会以为删掉就没了 —— 与数据保留策略当场打架。
      message: '删除后订单进入回收站（30 天内可由派单员恢复），确定删除该已撤销订单？',
    })
    await deleteCancelledOrder(o.id)
    router.back()
  } catch (e) {
    if (e !== 'cancel') {
      const err = e as { response?: { data?: { detail?: string } } }
      showFailToast(err.response?.data?.detail || '删除失败')
    }
  }
}
</script>

<template>
  <div class="odb" :class="{ 'odb--driver': isDriver }">
    <div class="head" :class="{ 'odb-hero': isDriver }">
      <div class="row1">
        <span class="no">{{ order.order_no }}</span>
        <van-tag :type="orderStatusTagType(order.status)" plain round size="medium">
          {{ ORDER_STATUS_LABEL[order.status] }}
        </van-tag>
      </div>
      <div class="muted">下单日期 {{ order.order_date }}</div>
    </div>

    <van-cell-group v-if="isDispatcher || isDriver" inset class="mt odb-group">
      <van-cell title="货主">
        <template #value>
          <span class="odb-strong">{{ emptyText(order.shipper_name, '—') }}</span>
        </template>
      </van-cell>
    </van-cell-group>

    <van-cell-group inset title="商品明细" class="mt odb-group">
      <van-cell
        v-for="ln in order.order_products"
        :key="ln.id"
        :title="ln.product_name_snapshot"
        :label="`单价 ¥${formatMoney2(ln.unit_price)} × ${ln.quantity}`"
      >
        <template #value>
          <span class="odb-price">¥{{ formatMoney2(ln.line_total) }}</span>
        </template>
      </van-cell>
    </van-cell-group>

    <van-cell-group inset title="送货信息" class="mt odb-group">
      <van-cell title="位置描述">
        <template #value>
          <span :class="{ 'odb-muted': !order.delivery_description?.trim() }">{{
            emptyText(order.delivery_description)
          }}</span>
        </template>
      </van-cell>
      <van-cell title="送达地址">
        <template #label>
          <div class="odb-addr" :class="{ 'odb-muted': !order.address_detail?.trim() }">
            {{ emptyText(order.address_detail, '未填写详细地址') }}
          </div>
        </template>
      </van-cell>
      <van-cell title="东家电话">
        <template #value>
          <span :class="{ 'odb-muted': !order.contact_dongjia_phone?.trim() }">{{
            emptyText(order.contact_dongjia_phone)
          }}</span>
        </template>
      </van-cell>
      <van-cell title="老板电话">
        <template #value>
          <span :class="{ 'odb-muted': !order.contact_boss_phone?.trim() }">{{
            emptyText(order.contact_boss_phone)
          }}</span>
        </template>
      </van-cell>
    </van-cell-group>

    <van-cell-group
      v-if="
        !isDriver &&
        (order.status === 'DISPATCHED' ||
          order.status === 'ACCEPTED' ||
          order.status === 'DELIVERED')
      "
      inset
      title="司机"
      class="mt"
    >
      <van-cell :title="order.driver_name || '司机'" :value="order.driver_phone || '—'" />
      <van-cell v-if="order.driver_phone" title="">
        <template #value>
          <van-button size="small" type="primary" @click="call(order.driver_phone!)">拨打电话</van-button>
        </template>
      </van-cell>
    </van-cell-group>

    <van-cell-group inset title="备注" class="mt odb-group">
      <van-cell>
        <template #title>
          <span class="lbl">备注</span>
        </template>
        <template #label>
          <div class="remark-body" :class="{ 'odb-muted': !order.remark?.trim() }">
            {{ order.remark?.trim() ? order.remark : '无' }}
          </div>
        </template>
      </van-cell>
    </van-cell-group>

    <van-cell-group v-if="isDispatcher || isDriver" inset class="mt odb-group">
      <van-cell title="内部备注">
        <template #label>
          <div
            class="remark-body"
            :class="{ 'odb-muted': !order.internal_notes?.trim() }"
          >
            {{ emptyText(order.internal_notes, '无') }}
          </div>
        </template>
      </van-cell>
    </van-cell-group>

    <van-cell-group inset class="mt odb-group">
      <van-cell title="司机备注">
        <template #label>
          <div
            class="remark-body"
            :class="{ 'odb-muted': !order.driver_remark?.trim() }"
          >
            {{ emptyText(order.driver_remark, '无') }}
          </div>
        </template>
      </van-cell>
    </van-cell-group>

    <van-cell-group
      v-if="isDispatcher && order.is_exception"
      inset
      title="异常"
      class="mt"
    >
      <van-cell v-if="order.exception_reason" title="原因" :label="order.exception_reason" />
      <van-cell v-if="order.exception_resolution" title="处理" :label="order.exception_resolution" />
    </van-cell-group>

    <van-cell-group
      v-if="order.status === 'DELIVERED' && photoUrls.length"
      inset
      title="送达照片"
      class="mt odb-group"
    >
      <div class="photos">
        <div
          v-for="(url, i) in photoUrls"
          :key="i"
          class="ph"
          @click="previewPhotos(photoUrls, i)"
        >
          <img v-lazy="url" alt="" />
          <div class="wm">{{ watermarkText }}</div>
        </div>
      </div>
      <van-cell title="水印说明" :label="watermarkText" />
    </van-cell-group>

    <div v-if="isShipper && CANCELLABLE_STATUSES.includes(order.status)" class="foot">
      <van-button type="danger" block round @click="tryCancel">撤销订单</van-button>
    </div>

    <div v-if="(isShipper || isDispatcher) && order.status === 'CANCELLED'" class="foot">
      <van-button type="danger" block round plain @click="tryDeleteCancelled">删除该订单</van-button>
    </div>
  </div>
</template>

<style scoped>
.odb {
  padding-bottom: 8px;
}

.odb--driver {
  padding-top: 4px;
  padding-bottom: max(16px, env(safe-area-inset-bottom));
}

.odb--driver .odb-hero {
  margin: 0 12px 14px;
  padding: 16px 16px 14px;
  background: linear-gradient(135deg, var(--van-background-2, #fff) 0%, rgba(22, 119, 255, 0.06) 100%);
  border-radius: 14px;
  border: 1px solid rgba(22, 119, 255, 0.12);
  box-shadow: 0 2px 12px rgba(15, 23, 42, 0.06);
}

.head:not(.odb-hero) {
  padding: 0 4px 12px;
}

.odb-hero .row1 {
  align-items: flex-start;
}

.row1 {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
}
.no {
  font-weight: 600;
  font-size: 16px;
  letter-spacing: -0.02em;
  line-height: 1.35;
}

.odb--driver .no {
  font-size: 18px;
}

.muted {
  font-size: 13px;
  color: var(--van-text-color-2);
  margin-top: 8px;
  line-height: 1.45;
}

.odb-group :deep(.van-cell-group__title) {
  padding: 16px 16px 8px;
  font-size: 15px;
  font-weight: 600;
  color: var(--van-text-color);
}

.odb-price {
  font-weight: 600;
  font-size: 16px;
  color: var(--van-danger-color, #ee0a24);
  font-variant-numeric: tabular-nums;
}

.odb-strong {
  font-weight: 500;
}

.odb-muted {
  color: var(--van-text-color-3, #c8c9cc);
}

.odb-addr {
  font-size: 14px;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
}

.mt {
  margin-top: 12px;
}
.photos {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 8px 16px 12px;
}
.ph {
  position: relative;
  width: 100px;
  height: 100px;
  border-radius: 8px;
  overflow: hidden;
}
.ph img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.wm {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  padding: 4px 6px;
  font-size: 9px;
  line-height: 1.2;
  color: #fff;
  background: linear-gradient(transparent, rgba(0, 0, 0, 0.65));
  max-height: 50%;
  overflow: hidden;
}
.foot {
  padding: 8px 0 0;
}
.lbl {
  font-weight: 500;
}
.remark-body {
  white-space: pre-wrap;
  font-size: 14px;
  line-height: 1.5;
  margin-top: 4px;
}
</style>
