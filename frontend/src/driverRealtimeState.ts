import { ref } from 'vue'

/** Increment to signal driver order lists to refetch (WS events). */
export const driverOrdersRefreshTick = ref(0)

export function bumpDriverOrdersRefresh() {
  driverOrdersRefreshTick.value += 1
}
