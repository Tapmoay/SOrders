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

export async function setQueueItemError(id: string, message: string): Promise<void> {
  const db = await openDb()
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
