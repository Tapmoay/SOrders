import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { fetchPendingDispatchCount } from '@/api/orders'

/** 派单员：待派单池订单数（与消息中心未读无关，用于 Tab/铃铛角标） */
export const useDispatcherWorkbenchStore = defineStore('dispatcherWorkbench', () => {
  const pendingDispatchCount = ref(0)
  /** 用户已进入派单工作台后暂时隐藏角标，直到待派单数高于当时快照 */
  const pendingPoolBadgeSuppressed = ref(false)
  const pendingCountWhenSuppressed = ref(0)

  function maybeUnsuppressAfterCountChange() {
    if (!pendingPoolBadgeSuppressed.value) return
    if (pendingDispatchCount.value > pendingCountWhenSuppressed.value) {
      pendingPoolBadgeSuppressed.value = false
    }
  }

  async function refreshPendingDispatchCount() {
    try {
      const { count } = await fetchPendingDispatchCount()
      pendingDispatchCount.value = Math.max(0, count)
      maybeUnsuppressAfterCountChange()
    } catch {
      /* 忽略：角标非关键路径 */
    }
  }

  /** 从其他页面/Tab 进入派单工作台时调用：收起待派单红点（仍跟踪真实数量） */
  function acknowledgePendingPoolBadge() {
    pendingPoolBadgeSuppressed.value = true
    pendingCountWhenSuppressed.value = pendingDispatchCount.value
  }

  /** 用于角标展示：抑制中为 0（不展示待派单数字） */
  const pendingPoolForBadge = computed(() => {
    if (pendingPoolBadgeSuppressed.value) return 0
    return pendingDispatchCount.value
  })

  function clear() {
    pendingDispatchCount.value = 0
    pendingPoolBadgeSuppressed.value = false
    pendingCountWhenSuppressed.value = 0
  }

  return {
    pendingDispatchCount,
    pendingPoolForBadge,
    refreshPendingDispatchCount,
    acknowledgePendingPoolBadge,
    clear,
  }
})
