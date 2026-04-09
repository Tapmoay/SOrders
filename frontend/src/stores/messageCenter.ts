import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import type { AppNotification } from '@/api/notifications'

const LAST_ID_KEY = 'sorders_last_notification_id'

function loadLastId(): number {
  try {
    const v = localStorage.getItem(LAST_ID_KEY)
    return v ? parseInt(v, 10) || 0 : 0
  } catch {
    return 0
  }
}

export const useMessageCenterStore = defineStore('messageCenter', () => {
  const unreadCount = ref(0)
  const lastNotificationId = ref(loadLastId())
  const items = ref<AppNotification[]>([])

  const hasUnread = computed(() => unreadCount.value > 0)

  function persistLastId(id: number) {
    if (id > lastNotificationId.value) {
      lastNotificationId.value = id
      try {
        localStorage.setItem(LAST_ID_KEY, String(id))
      } catch {
        /* ignore */
      }
    }
  }

  function setUnread(n: number) {
    unreadCount.value = Math.max(0, n)
  }

  function mergeFromSync(list: AppNotification[]) {
    const seen = new Set(items.value.map((x) => x.id))
    for (const n of list) {
      persistLastId(n.id)
      if (!seen.has(n.id)) {
        items.value.unshift(n)
        seen.add(n.id)
      }
    }
    items.value.sort((a, b) => b.id - a.id)
  }

  function addIncoming(n: AppNotification) {
    persistLastId(n.id)
    const i = items.value.findIndex((x) => x.id === n.id)
    if (i >= 0) items.value[i] = n
    else items.value.unshift(n)
  }

  function removeById(id: number) {
    items.value = items.value.filter((x) => x.id !== id)
  }

  function clearLocal() {
    items.value = []
  }

  function setItems(list: AppNotification[]) {
    items.value = list.slice()
  }

  return {
    unreadCount,
    lastNotificationId,
    items,
    hasUnread,
    persistLastId,
    setUnread,
    mergeFromSync,
    addIncoming,
    removeById,
    clearLocal,
    setItems,
  }
})
