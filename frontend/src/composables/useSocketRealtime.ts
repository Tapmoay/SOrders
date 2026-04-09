import { io, type Socket } from 'socket.io-client'
import { onUnmounted, watch } from 'vue'

import {
  fetchNotifications,
  fetchUnreadCount,
  type AppNotification,
} from '@/api/notifications'
import { bumpDriverOrdersRefresh } from '@/driverRealtimeState'
import { bumpShipperOrdersRefresh } from '@/shipperRealtimeState'
import { useAuthStore } from '@/stores/auth'
import { useMessageCenterStore } from '@/stores/messageCenter'

let socket: Socket | null = null

function speakImportant(text: string) {
  try {
    if (!window.speechSynthesis) return
    window.speechSynthesis.cancel()
    const u = new SpeechSynthesisUtterance(text)
    u.lang = 'zh-CN'
    window.speechSynthesis.speak(u)
  } catch {
    /* ignore */
  }
}

function shouldBumpDriver(t: string) {
  return (
    t === 'order.assigned' ||
    t === 'order.revoked' ||
    t === 'order.cancelled' ||
    t === 'order.delivered'
  )
}

function shouldBumpShipper(t: string) {
  return (
    t === 'order.dispatched' ||
    t === 'order.recalled' ||
    t === 'order.cancelled' ||
    t === 'order.delivered' ||
    t === 'order.driver_ack' ||
    t === 'ledger.updated'
  )
}

export function useSocketRealtime() {
  const auth = useAuthStore()
  const msg = useMessageCenterStore()

  function teardown() {
    try {
      socket?.disconnect()
    } catch {
      /* ignore */
    }
    socket = null
  }

  function bindHandlers(s: Socket) {
    s.off('sync')
    s.off('notification')
    s.off('unread_count')
    s.off('realtime')

    s.on('sync', (payload: { notifications: AppNotification[]; unread_count: number }) => {
      msg.mergeFromSync(payload.notifications || [])
      msg.setUnread(payload.unread_count ?? 0)
    })

    s.on('notification', (payload: { notification: AppNotification }) => {
      const n = payload?.notification
      if (!n) return
      msg.addIncoming(n)
      if (n.speech_important) {
        speakImportant(`${n.title}。${n.content || ''}`.trim())
      }
    })

    s.on('unread_count', (payload: { count: number }) => {
      msg.setUnread(payload?.count ?? 0)
    })

    s.on('realtime', (ev: { type?: string }) => {
      const t = ev?.type || ''
      if (auth.role === 'driver' && shouldBumpDriver(t)) {
        bumpDriverOrdersRefresh()
      }
      if (auth.role === 'shipper' && shouldBumpShipper(t)) {
        bumpShipperOrdersRefresh()
      }
    })
  }

  function connect() {
    if (!auth.token || !auth.role) {
      teardown()
      return
    }
    teardown()
    const s = io({
      path: '/socket.io',
      transports: ['websocket', 'polling'],
      reconnection: true,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 30000,
      auth: () => ({
        token: auth.token || localStorage.getItem('access_token') || '',
        lastNotificationId: msg.lastNotificationId,
      }),
    })
    socket = s
    bindHandlers(s)
    s.connect()
  }

  watch(
    () => [auth.token, auth.role] as const,
    async ([t, r]) => {
      if (t && r) {
        try {
          const c = await fetchUnreadCount()
          msg.setUnread(c)
          const list = await fetchNotifications({ unread_only: false })
          msg.setItems(list)
        } catch {
          /* ignore */
        }
        connect()
      } else {
        teardown()
        msg.clearLocal()
        msg.setUnread(0)
      }
    },
    { immediate: true },
  )

  onUnmounted(() => {
    teardown()
  })

  return { connect, disconnect: teardown }
}
