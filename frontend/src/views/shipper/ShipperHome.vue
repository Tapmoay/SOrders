<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { clearOrderDraft, orderDraftIsResumable } from '@/constants/orderDraft'
import { reconcileShipperOrderDraftStale } from '@/utils/orderDraftSync'

const router = useRouter()
const hasDraft = ref(false)

function refreshDraftFlag() {
  hasDraft.value = orderDraftIsResumable('shipper')
}

/** 左侧：清空草稿并打开空白下单页 */
function goNewOrder() {
  clearOrderDraft('shipper')
  refreshDraftFlag()
  void router.push({ path: '/shipper/orders/create' })
}

/** 右侧：仅继续编辑已保存的草稿 */
function goResumeDraft() {
  void router.push({ path: '/shipper/orders/create', query: { resume: '1' } })
}

onMounted(async () => {
  await reconcileShipperOrderDraftStale()
  refreshDraftFlag()
})
</script>

<template>
  <div class="shipper-home">
    <p class="shipper-home__intro">下单与常用入口</p>

    <!-- 整卡模块：全宽蓝顶栏 + 白内容区（与旧版「左侧小标签」明显不同） -->
    <section class="module module-order">
      <header class="module__hd">
        <span class="module__title">下单</span>
      </header>
      <div class="module__bd">
        <div class="order-card" role="presentation">
          <div class="order-card__main" role="button" tabindex="0" @click="goNewOrder">
            <div class="order-card__icon">
              <van-icon name="orders-o" size="26" />
            </div>
            <div class="order-card__text">
              <span class="order-card__title">新建订单</span>
              <span class="order-card__sub">
                {{
                  hasDraft
                    ? '左侧：空白新单（会清除当前草稿）；右侧：继续编辑草稿'
                    : '填写收货信息与商品明细'
                }}
              </span>
            </div>
            <van-icon v-if="!hasDraft" name="arrow" class="order-card__arrow" />
          </div>
          <button
            v-if="hasDraft"
            type="button"
            class="draft-resume"
            aria-label="继续编辑未提交草稿"
            @click.stop="goResumeDraft"
          >
            <span class="draft-resume__warn"><van-icon name="warning-o" /></span>
            <span class="draft-resume__label">继续草稿</span>
          </button>
        </div>
      </div>
    </section>

    <section class="module module-mine">
      <header class="module__hd">
        <span class="module__title">我的</span>
      </header>
      <div class="module__bd module__bd--cells">
        <van-cell-group :border="false">
          <van-cell title="我的订单" is-link @click="router.push('/shipper/orders')" />
          <van-cell
            title="已送达订单"
            label="仅查看已完成配送"
            is-link
            @click="router.push({ path: '/shipper/orders', query: { tab: 'delivered' } })"
          />
          <van-cell title="我的账本" is-link @click="router.push('/shipper/ledger')" />
          <van-cell title="常用地址和信息" is-link @click="router.push('/shipper/addresses')" />
        </van-cell-group>
      </div>
    </section>
  </div>
</template>

<style scoped>
.shipper-home {
  padding: 8px 0 28px;
  background: var(--van-background);
  min-height: 60vh;
}

.shipper-home__intro {
  margin: 4px 20px 14px;
  font-size: 13px;
  font-weight: 500;
  color: var(--van-text-color-2);
  letter-spacing: 0.02em;
}

/* 整块卡片：全宽蓝顶栏；顶栏压扁上下高度（非缩短横向） */
.module {
  --mod-r: 14px;
  margin: 0 16px 20px;
  border-radius: var(--mod-r);
  overflow: hidden;
  background: var(--van-background-2);
  border: 1px solid rgba(22, 119, 255, 0.12);
  box-shadow:
    0 4px 18px rgba(22, 119, 255, 0.07),
    0 1px 3px rgba(15, 23, 42, 0.06);
}

.module__hd {
  margin: 0;
  padding: 6px 16px;
  background: linear-gradient(135deg, #1677ff 0%, #0958d9 100%);
  border-bottom: 1px solid rgba(255, 255, 255, 0.12);
}

.module__title {
  display: block;
  font-size: 15px;
  font-weight: 600;
  line-height: 1.25;
  color: #fff;
  letter-spacing: 0.03em;
}

.module__bd {
  background: var(--van-background-2);
}

.module__bd--cells :deep(.van-cell) {
  background: var(--van-background-2);
}

.module__bd--cells :deep(.van-cell__title) {
  font-weight: 500;
  font-size: 16px;
  color: var(--van-text-color);
}

.module__bd--cells :deep(.van-cell:last-child::after) {
  display: none;
}

.order-card {
  display: flex;
  align-items: stretch;
  gap: 0;
  min-height: 56px;
}

.order-card__main {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0;
  padding: 18px 12px 18px 16px;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
  transition: background-color 0.18s ease;
}

.order-card__main:active {
  background: var(--van-active-color);
}

.order-card__icon {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 48px;
  height: 48px;
  border-radius: 10px;
  background: rgba(22, 119, 255, 0.1);
  color: var(--van-primary-color, #1677ff);
}

.order-card__text {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.order-card__title {
  font-size: 17px;
  font-weight: 600;
  line-height: 1.35;
  color: var(--van-text-color);
}

.order-card__sub {
  font-size: 12px;
  line-height: 1.45;
  color: var(--van-text-color-2);
}

.order-card__arrow {
  flex-shrink: 0;
  color: var(--van-text-color-3);
  font-size: 18px;
}

.draft-resume {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  width: 72px;
  flex-shrink: 0;
  margin: 0;
  padding: 10px 8px;
  border: none;
  border-left: 1px solid var(--van-border-color);
  background: rgba(238, 10, 36, 0.06);
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
  font: inherit;
  color: var(--van-text-color);
}

.draft-resume:active {
  background: rgba(238, 10, 36, 0.12);
}

.draft-resume__warn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  font-size: 18px;
  color: #ee0a24;
  background: #fff;
  border-radius: 50%;
  box-shadow: 0 0 0 1px rgba(238, 10, 36, 0.2);
}

.draft-resume__label {
  font-size: 11px;
  font-weight: 600;
  line-height: 1.2;
  color: #ee0a24;
  max-width: 100%;
  text-align: center;
}
</style>
