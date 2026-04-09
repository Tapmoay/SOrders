import { ref } from 'vue'

/** 货主订单列表在收到派单/撤回等 WS 事件时递增以触发刷新 */
export const shipperOrdersRefreshTick = ref(0)

export function bumpShipperOrdersRefresh() {
  shipperOrdersRefreshTick.value += 1
}
