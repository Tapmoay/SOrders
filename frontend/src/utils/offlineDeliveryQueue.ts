const DB = 'sorders_driver'
const STORE = 'delivery_queue'
const VER = 1

export interface OfflineDeliveryQueueItem {
  id: string
  orderId: number
  /** 展示用 */
  orderNo?: string
  driverRemark: string
  /** 联网同步时先 appendDriverNote，再上传送达照 */
  internalNoteAppend?: string
  /**
   * 那条追加备注**是否已经写进服务端**了。
   *
   * ⚠️ 为什么必须持久化这个标记（2026-09-19 审计）：同步是"追加备注 → 上传照片"两步，
   * 而重试是**整条重来**。第二次走的时候如果还去 append，订单的内部备注里就会出现
   * 两遍、三遍同一句话（"司机说货主让放门口"重复三行）——而派单员正是靠内部备注判断现场发生了什么。
   * 上传失败是常事（信号差），所以这不是边角情况。
   */
  noteAppended?: boolean
  blobs: Blob[]
  createdAt: number
  retries: number
  lastError?: string
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB, VER)
    req.onupgradeneeded = () => {
      const db = req.result
      if (!db.objectStoreNames.contains(STORE)) {
        db.createObjectStore(STORE, { keyPath: 'id' })
      }
    }
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
}

export async function queueOfflineDelivery(item: OfflineDeliveryQueueItem): Promise<void> {
  const db = await openDb()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, 'readwrite')
    tx.objectStore(STORE).put(item)
    tx.oncomplete = () => resolve()
    tx.onerror = () => reject(tx.error)
  })
}

export async function listOfflineQueue(): Promise<OfflineDeliveryQueueItem[]> {
  const db = await openDb()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, 'readonly')
    const req = tx.objectStore(STORE).getAll()
    req.onsuccess = () => resolve((req.result as OfflineDeliveryQueueItem[]) ?? [])
    req.onerror = () => reject(req.error)
  })
}

export async function removeOfflineQueueItem(id: string): Promise<void> {
  const db = await openDb()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, 'readwrite')
    tx.objectStore(STORE).delete(id)
    tx.oncomplete = () => resolve()
    tx.onerror = () => reject(tx.error)
  })
}

export async function bumpRetry(id: string): Promise<void> {
  const db = await openDb()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, 'readwrite')
    const st = tx.objectStore(STORE)
    const g = st.get(id)
    g.onsuccess = () => {
      const row = g.result as OfflineDeliveryQueueItem | undefined
      if (row) {
        row.retries += 1
        st.put(row)
      }
    }
    tx.oncomplete = () => resolve()
    tx.onerror = () => reject(tx.error)
  })
}

/**
 * 记下"这条队列项的追加备注已经写进服务端了"。
 *
 * ⚠️ 必须**先写标记、再上传照片**（顺序反了就等于没记）：上传失败会重试整条，
 * 而重试时靠这个标记跳过 append，否则内部备注会被追加多遍。
 */
export async function markNoteAppended(id: string): Promise<void> {
  const db = await openDb()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, 'readwrite')
    const st = tx.objectStore(STORE)
    const g = st.get(id)
    g.onsuccess = () => {
      const row = g.result as OfflineDeliveryQueueItem | undefined
      if (row) {
        row.noteAppended = true
        st.put(row)
      }
    }
    tx.oncomplete = () => resolve()
    tx.onerror = () => reject(tx.error)
  })
}

export async function setQueueItemError(id: string, message: string): Promise<void> {  const db = await openDb()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, 'readwrite')
    const st = tx.objectStore(STORE)
    const g = st.get(id)
    g.onsuccess = () => {
      const row = g.result as OfflineDeliveryQueueItem | undefined
      if (row) {
        row.lastError = message.slice(0, 500)
        st.put(row)
      }
    }
    tx.oncomplete = () => resolve()
    tx.onerror = () => reject(tx.error)
  })
}
