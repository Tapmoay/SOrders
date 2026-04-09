<script setup lang="ts">
import { computed } from 'vue'

import { fetchUnreadCount, markNotificationRead, type AppNotification } from '@/api/notifications'
import { useMessageCenterStore } from '@/stores/messageCenter'
import { resolveStaticUrl } from '@/utils/assets'

const emit = defineEmits<{ openMessages: [] }>()

const msg = useMessageCenterStore()

const row = computed(
  () => msg.items.find((n) => n.type === 'price_change' && !n.read_at) as AppNotification | undefined,
)

const pay = computed(() => (row.value?.payload || {}) as Record<string, unknown>)

const img = computed(() => {
  const u = pay.value.product_image_url
  return typeof u === 'string' && u ? resolveStaticUrl(u) : ''
})

async function onClose() {
  const n = row.value
  if (!n) return
  try {
    await markNotificationRead(n.id)
    n.read_at = new Date().toISOString()
    msg.setUnread(await fetchUnreadCount())
  } catch {
    /* ignore */
  }
}

function onOpen() {
  emit('openMessages')
}
</script>

<template>
  <div v-if="row" class="spn" role="button" @click="onOpen">
    <img v-if="img" :src="img" alt="" class="spn__img" />
    <div class="spn__body">
      <div class="spn__title">{{ row.title }}</div>
      <div class="spn__line">
        <span class="spn__type">{{
          pay.price_type === 'special' ? '货主特殊价' : '全局默认价'
        }}</span>
        <span v-if="pay.old_price != null && String(pay.old_price) !== ''" class="spn__old">{{
          pay.old_price
        }}</span>
        <span
          v-if="pay.old_price != null && pay.new_price != null"
          class="spn__arrow"
        >
          →
        </span>
        <span class="spn__new">{{ pay.new_price }}</span>
        <span class="spn__hint">（价格变动）</span>
      </div>
    </div>
    <van-icon name="cross" class="spn__x" @click.stop="onClose" />
  </div>
</template>

<style scoped>
.spn {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  margin: 0 0 0;
  background: linear-gradient(90deg, rgba(255, 247, 230, 1) 0%, rgba(255, 255, 255, 1) 100%);
  border-bottom: 1px solid rgba(255, 183, 77, 0.45);
  box-shadow: 0 2px 8px rgba(250, 140, 22, 0.12);
}
.spn__img {
  width: 48px;
  height: 48px;
  border-radius: 8px;
  object-fit: cover;
  flex-shrink: 0;
  border: 1px solid rgba(0, 0, 0, 0.06);
}
.spn__body {
  flex: 1;
  min-width: 0;
}
.spn__title {
  font-size: 14px;
  font-weight: 600;
  color: var(--van-text-color);
  line-height: 1.35;
  margin-bottom: 4px;
}
.spn__line {
  font-size: 13px;
  line-height: 1.4;
  color: var(--van-text-color-2);
}
.spn__type {
  margin-right: 6px;
  color: var(--van-primary-color);
  font-weight: 500;
}
.spn__old {
  text-decoration: line-through;
  opacity: 0.75;
}
.spn__arrow {
  margin: 0 4px;
  color: var(--van-text-color-3);
}
.spn__new {
  font-weight: 700;
  color: #d4380d;
}
.spn__hint {
  margin-left: 6px;
  font-size: 12px;
  color: #d4380d;
}
.spn__x {
  flex-shrink: 0;
  padding: 8px;
  color: var(--van-text-color-3);
  font-size: 18px;
}
</style>
