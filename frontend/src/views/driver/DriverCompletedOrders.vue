<script setup lang="ts">
import { showImagePreview } from 'vant'
import { onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { fetchOrders } from '@/api/orders'
import VirtualScrollList from '@/components/VirtualScrollList.vue'
import { driverOrdersRefreshTick } from '@/driverRealtimeState'
import { ORDER_STATUS_LABEL } from '@/constants/order'
import type { Order } from '@/types/order'

const router = useRouter()
const loading = ref(false)
const refreshing = ref(false)
const list = ref<Order[]>([])

function goOrderDetail(id: number) {
  router.push({ name: 'driver-order-detail', params: { id: String(id) } })
}

function ord(x: unknown): Order {
  return x as Order
}

function staticUrl(u: string) {
  if (!u) return ''
  if (u.startsWith('http')) return u
  return u.startsWith('/') ? u : `/${u}`
}

function productLine(o: Order) {
  if (!o.order_products?.length) return o.delivery_description || '—'
  return o.order_products.map((p) => `${p.product_name_snapshot}×${p.quantity}`).join('；')
}

function addrLine(o: Order) {
  const t = o.address_detail?.trim() || ''
  return t || ''
}

function fmtDelivered(iso: string | null | undefined) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getMonth() + 1}/${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

function previewDeliveryPhotos(urls: string[] | null | undefined, start: number) {
  const u = (urls || []).filter(Boolean)
  if (!u.length) return
  showImagePreview({
    images: u.map(staticUrl),
    startPosition: start,
  })
}

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    list.value = await fetchOrders('DELIVERED')
  } finally {
    if (!silent) loading.value = false
  }
}

async function onRefresh() {
  await load(true)
  refreshing.value = false
}

watch(driverOrdersRefreshTick, () => {
  void load(true)
})

onMounted(() => {
  void load()
})
</script>

<template>
  <div class="driver-done role-tool-page">
    <van-pull-refresh v-model="refreshing" @refresh="onRefresh">
      <van-empty v-if="!loading && !list.length" description="暂无已完成订单" />
      <VirtualScrollList v-else :items="list" :estimate-size="280">
        <template #default="{ item }">
          <div
            v-for="o in [ord(item)]"
            :key="o.id"
            class="dcard"
            role="button"
            tabindex="0"
            :aria-label="`订单 ${o.order_no}，点击查看详情`"
            @click="goOrderDetail(o.id)"
            @keydown.enter.prevent="goOrderDetail(o.id)"
            @keydown.space.prevent="goOrderDetail(o.id)"
          >
            <div class="dcard__top">
              <div class="dcard__titles">
                <span class="dcard__no">{{ o.order_no }}</span>
                <p v-if="fmtDelivered(o.delivered_at)" class="dcard__time">
                  <van-icon name="clock-o" class="dcard__time-ico" />
                  送达 {{ fmtDelivered(o.delivered_at) }}
                </p>
              </div>
              <van-tag type="success" plain round size="medium">{{ ORDER_STATUS_LABEL[o.status] }}</van-tag>
            </div>

            <div class="dcard__body">
              <div class="dcard__row">
                <span class="dcard__label">货主</span>
                <span class="dcard__val">{{ o.shipper_name?.trim() || '—' }}</span>
              </div>
              <div class="dcard__row">
                <span class="dcard__label">地址</span>
                <span class="dcard__val" :class="{ 'dcard__val--empty': !addrLine(o) }">
                  {{ addrLine(o) || '未填写' }}
                </span>
              </div>
              <div class="dcard__row">
                <span class="dcard__label">商品</span>
                <span class="dcard__val dcard__val--emph">{{ productLine(o) }}</span>
              </div>
              <div v-if="o.driver_remark?.trim()" class="dcard__row">
                <span class="dcard__label">备注</span>
                <span class="dcard__val">{{ o.driver_remark }}</span>
              </div>
            </div>

            <div v-if="o.delivery_photo_urls?.length" class="dcard__photos">
              <div class="dcard__photos-hd">
                <van-icon name="photo-o" />
                送达凭证
              </div>
              <div class="dcard__grid">
                <img
                  v-for="(src, i) in o.delivery_photo_urls"
                  :key="i"
                  v-lazy="staticUrl(src)"
                  alt="送达照片"
                  class="dcard__thumb"
                  @click.stop="previewDeliveryPhotos(o.delivery_photo_urls, i)"
                />
              </div>
            </div>

            <div class="dcard__foot">
              点击查看订单详情
              <van-icon name="arrow" />
            </div>
          </div>
        </template>
      </VirtualScrollList>
    </van-pull-refresh>
  </div>
</template>

<style scoped>
.driver-done {
  min-height: 100%;
  padding: 10px 12px max(20px, env(safe-area-inset-bottom));
  background: var(--van-background, #f7f8fa);
}

.dcard {
  background: var(--van-background-2, #fff);
  border-radius: 14px;
  margin-bottom: 14px;
  overflow: hidden;
  border: 1px solid rgba(15, 23, 42, 0.06);
  box-shadow: 0 2px 14px rgba(15, 23, 42, 0.06);
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
  transition: transform 0.12s ease, box-shadow 0.12s ease;
}

.dcard:active {
  transform: scale(0.992);
  box-shadow: 0 1px 8px rgba(15, 23, 42, 0.08);
}

.dcard:focus-visible {
  outline: 2px solid var(--van-primary-color, #1677ff);
  outline-offset: 2px;
}

.dcard__top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 10px;
  padding: 14px 14px 12px;
  background: linear-gradient(180deg, rgba(22, 119, 255, 0.06) 0%, transparent 100%);
  border-bottom: 1px solid var(--van-border-color, #ebedf0);
}

.dcard__titles {
  min-width: 0;
  flex: 1;
}

.dcard__no {
  display: inline-block;
  font-size: 17px;
  font-weight: 600;
  letter-spacing: -0.02em;
  color: var(--van-primary-color, #1677ff);
  text-decoration: none;
  line-height: 1.3;
}

.dcard__time {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--van-text-color-2, #646566);
  display: flex;
  align-items: center;
  gap: 4px;
}

.dcard__time-ico {
  font-size: 14px;
  opacity: 0.85;
}

.dcard__body {
  padding: 12px 14px 4px;
}

.dcard__row {
  display: flex;
  gap: 12px;
  margin-bottom: 10px;
  font-size: 14px;
  line-height: 1.45;
}

.dcard__row:last-child {
  margin-bottom: 0;
}

.dcard__label {
  flex-shrink: 0;
  width: 40px;
  font-size: 12px;
  font-weight: 500;
  color: var(--van-text-color-2, #646566);
  letter-spacing: 0.02em;
  padding-top: 1px;
}

.dcard__val {
  flex: 1;
  min-width: 0;
  color: var(--van-text-color, #323233);
  word-break: break-word;
}

.dcard__val--empty {
  color: var(--van-text-color-3, #c8c9cc);
  font-style: normal;
}

.dcard__val--emph {
  font-weight: 500;
}

.dcard__photos {
  padding: 0 14px 12px;
}

.dcard__photos-hd {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 500;
  color: var(--van-text-color-2, #646566);
  margin-bottom: 8px;
}

.dcard__grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.dcard__thumb {
  width: 80px;
  height: 80px;
  object-fit: cover;
  border-radius: 8px;
  border: 1px solid var(--van-border-color, #ebedf0);
  cursor: zoom-in;
}

.dcard__foot {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 11px 14px;
  font-size: 13px;
  font-weight: 500;
  color: var(--van-text-color-2, #646566);
  background: rgba(22, 119, 255, 0.04);
  border-top: 1px solid var(--van-border-color, #ebedf0);
}

.dcard__foot .van-icon {
  font-size: 14px;
  color: var(--van-primary-color, #1677ff);
  opacity: 0.9;
}
</style>
