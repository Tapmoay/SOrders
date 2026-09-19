<script setup lang="ts">
import { showConfirmDialog, showFailToast, showSuccessToast } from 'vant'
import { computed, ref, watch } from 'vue'

import {
  deleteNotification,
  fetchNotificationsPage,
  fetchUnreadCount,
  markAllNotificationsRead,
  markNotificationRead,
  type AppNotification,
  type MessageCategory,
} from '@/api/notifications'
import { useMessageCenterStore } from '@/stores/messageCenter'

const props = defineProps<{ show: boolean }>()
const emit = defineEmits<{ 'update:show': [boolean] }>()

const msg = useMessageCenterStore()
const tab = ref<'all' | MessageCategory>('all')
const loading = ref(false)
/** 服务端把这一页截断了（`X-Truncated`）：界面必须说出来，否则用户以为「这就是全部」 */
const truncated = ref(false)
/** 服务端本次的上限（`X-Result-Limit`）；读不到时为空 */
const resultLimit = ref<number | null>(null)

const titleMap: Record<string, string> = {
  all: '全部',
  system: '系统',
  order: '订单',
  reminder: '提醒',
}

const displayList = computed(() => {
  const raw = msg.items
  if (tab.value === 'all') return raw
  return raw.filter((x) => (x.category || 'order') === tab.value)
})

async function loadList() {
  loading.value = true
  try {
    const params =
      tab.value === 'all' ? undefined : { category: tab.value as MessageCategory }
    // 服务端对消息列表有硬上限（200 条），必须把「被截断」这件事取回来并说出来：
    // 第 201 条以前的旧消息在界面上一个入口都没有，其中包含带唯一下载链接的通知。
    const page = await fetchNotificationsPage(params)
    msg.setItems(page.items)
    truncated.value = page.truncated
    resultLimit.value = page.limit
  } catch {
    showFailToast('加载消息失败')
  } finally {
    loading.value = false
  }
}

watch(
  () => props.show,
  (v) => {
    if (v) void loadList()
  },
)

watch(tab, () => {
  if (props.show) void loadList()
})

watch(tab, () => {
  if (props.show) void loadList()
})

function close() {
  emit('update:show', false)
}

async function onRead(row: AppNotification) {
  if (row.read_at) return
  try {
    await markNotificationRead(row.id)
    row.read_at = new Date().toISOString()
    const c = await fetchUnreadCount()
    msg.setUnread(c)
  } catch {
    showFailToast('操作失败')
  }
}

async function onDelete(row: AppNotification) {
  try {
    await showConfirmDialog({ title: '删除消息', message: '确定删除该条消息？' })
    await deleteNotification(row.id)
    msg.removeById(row.id)
    msg.setUnread(await fetchUnreadCount())
    showSuccessToast('已删除')
  } catch (e) {
    if (e !== 'cancel') showFailToast('删除失败')
  }
}

async function onReadAll() {
  try {
    await markAllNotificationsRead()
    await loadList()
    msg.setUnread(0)
    showSuccessToast('已全部标为已读')
  } catch {
    showFailToast('操作失败')
  }
}

function catLabel(row: AppNotification) {
  const c = row.category || 'order'
  return titleMap[c] || c
}
</script>

<template>
  <van-popup
    :show="show"
    position="right"
    :style="{ width: '92%', height: '100%' }"
    @update:show="emit('update:show', $event)"
  >
    <div class="mc">
      <van-nav-bar title="消息中心" left-text="关闭" @click-left="close">
        <template #right>
          <van-button size="small" type="primary" plain @click="onReadAll">全部已读</van-button>
        </template>
      </van-nav-bar>

      <van-tabs v-model:active="tab" shrink>
        <van-tab title="全部" name="all" />
        <van-tab title="系统" name="system" />
        <van-tab title="订单" name="order" />
        <van-tab title="提醒" name="reminder" />
      </van-tabs>

      <van-notice-bar
        v-if="truncated"
        left-icon="info-o"
        wrapable
        :scrollable="false"
        text="更早的消息没有列出来（服务端一次最多返回 200 条）——「全部已读」只作用于已加载的这些。"
      />
      <van-loading v-if="loading" vertical class="ld">加载中</van-loading>
      <van-empty v-else-if="!displayList.length" description="暂无消息" />
      <van-cell-group v-else inset>
        <van-swipe-cell v-for="row in displayList" :key="row.id">
          <van-cell
            :title="row.title"
            :label="row.content"
            is-link
            @click="onRead(row)"
          >
            <template #value>
              <div class="meta">
                <van-tag v-if="!row.read_at" type="danger" plain size="medium">未读</van-tag>
                <van-tag plain size="medium" class="tag-cat">{{ catLabel(row) }}</van-tag>
              </div>
            </template>
          </van-cell>
          <template #right>
            <van-button square type="danger" text="删除" class="sw-btn" @click="onDelete(row)" />
          </template>
        </van-swipe-cell>
      </van-cell-group>
    </div>
  </van-popup>
</template>

<style scoped>
.mc {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--van-background, #f7f8fa);
}
.ld {
  padding: 24px;
}
.meta {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
}
.tag-cat {
  margin-top: 2px;
}
.sw-btn {
  height: 100%;
}
</style>
