/** 订单刷新已迁移至 useSocketRealtime（Socket.IO）。保留空实现以兼容旧引用。 */
export function useShipperRealtime() {
  return { disconnect: () => {} }
}
