import { http } from './client'

export type MessageCategory = 'system' | 'order' | 'reminder'

export interface AppNotification {
  id: number
  recipient_id: number
  category: MessageCategory
  type: string
  speech_important: boolean
  title: string
  content: string
  payload: Record<string, unknown> | null
  read_at: string | null
  created_at: string
}

export async function fetchUnreadCount() {
  const { data } = await http.get<{ count: number }>('/notifications/unread-count')
  return data.count
}

/** 与 `api/orders.ts::OrdersPage` 同一套判据：列表 + 这次是不是被服务端截断了。 */
export interface NotificationsPage {
  items: AppNotification[]
  truncated: boolean
  limit: number | null
}

/**
 * ⚠️ **必须看响应头**（2026-09-19 审计 H2）：`GET /notifications` 是一条硬 `.limit(200)`
 * 上限（实测派单员账号 2336 条）。不看这两个头，界面就会显示"这就是全部" ——
 * 而第 201 条以前的旧消息里包含「账本导出完成」这种 payload 带**唯一下载链接**的通知
 * （链接过期就再也拿不到）；用户点「全部已读」把它标掉，其实只看过 200 条。
 */
export async function fetchNotificationsPage(params?: {
  unread_only?: boolean
  category?: MessageCategory
}): Promise<NotificationsPage> {
  const res = await http.get<AppNotification[]>('/notifications', { params })
  const h = res.headers as Record<string, unknown>
  const raw = h['x-truncated']
  const lim = h['x-result-limit']
  const limit = lim != null && String(lim).trim() !== '' ? Number(lim) : null
  return {
    items: res.data,
    truncated: raw === '1' || raw === 'true' || raw === true,
    limit: Number.isFinite(limit as number) ? (limit as number) : null,
  }
}

export async function fetchNotifications(params?: {
  unread_only?: boolean
  category?: MessageCategory
}) {
  const page = await fetchNotificationsPage(params)
  return page.items
}

export async function markNotificationRead(id: number) {
  const { data } = await http.post<AppNotification>(`/notifications/${id}/read`)
  return data
}

export async function markAllNotificationsRead() {
  const { data } = await http.post<{ updated: number }>('/notifications/read-all')
  return data
}

export async function deleteNotification(id: number) {
  await http.delete(`/notifications/${id}`)
}
