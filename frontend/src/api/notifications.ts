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

export async function fetchNotifications(params?: {
  unread_only?: boolean
  category?: MessageCategory
}) {
  const { data } = await http.get<AppNotification[]>('/notifications', { params })
  return data
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
