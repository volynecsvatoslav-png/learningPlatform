import type { OfflineChunk, OfflinePackage } from './types'

const DB_NAME = 'learning-platform-offline'
const DB_VERSION = 1

function requestResult<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => { resolve(request.result) }
    request.onerror = () => { reject(request.error ?? new Error('INDEXED_DB_ERROR')) }
  })
}

function transactionDone(transaction: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => { resolve() }
    transaction.onerror = () => { reject(transaction.error ?? new Error('INDEXED_DB_ERROR')) }
    transaction.onabort = () => { reject(transaction.error ?? new Error('INDEXED_DB_ABORTED')) }
  })
}

export function openOfflineDb(): Promise<IDBDatabase> {
  if (!('indexedDB' in globalThis)) return Promise.reject(new Error('OFFLINE_STORAGE_UNAVAILABLE'))
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION)
    request.onupgradeneeded = () => {
      const db = request.result
      if (!db.objectStoreNames.contains('packages')) db.createObjectStore('packages', { keyPath: 'courseId' })
      if (!db.objectStoreNames.contains('keys')) db.createObjectStore('keys', { keyPath: 'id' })
      if (!db.objectStoreNames.contains('chunks')) {
        const chunks = db.createObjectStore('chunks', { keyPath: 'id' })
        chunks.createIndex('packageId', 'packageId')
      }
    }
    request.onsuccess = () => { resolve(request.result) }
    request.onerror = () => { reject(request.error ?? new Error('INDEXED_DB_ERROR')) }
  })
}

export async function putPackage(value: OfflinePackage): Promise<void> {
  const db = await openOfflineDb()
  const transaction = db.transaction('packages', 'readwrite')
  transaction.objectStore('packages').put(value)
  await transactionDone(transaction)
  db.close()
}

export async function getPackage(courseId: string): Promise<OfflinePackage | undefined> {
  const db = await openOfflineDb()
  const value = await requestResult(db.transaction('packages').objectStore('packages').get(courseId)) as OfflinePackage | undefined
  db.close()
  return value
}

export async function getPackages(): Promise<OfflinePackage[]> {
  const db = await openOfflineDb()
  const values = await requestResult(db.transaction('packages').objectStore('packages').getAll()) as OfflinePackage[]
  db.close()
  return values
}

export async function deletePackageRecord(courseId: string): Promise<void> {
  const db = await openOfflineDb()
  const transaction = db.transaction('packages', 'readwrite')
  transaction.objectStore('packages').delete(courseId)
  await transactionDone(transaction)
  db.close()
}

export async function putKey(id: string, key: CryptoKey): Promise<void> {
  const db = await openOfflineDb()
  const transaction = db.transaction('keys', 'readwrite')
  transaction.objectStore('keys').put({ id, key })
  await transactionDone(transaction)
  db.close()
}

export async function getKey(id: string): Promise<CryptoKey | undefined> {
  const db = await openOfflineDb()
  const value = await requestResult(db.transaction('keys').objectStore('keys').get(id)) as { id: string; key: CryptoKey } | undefined
  db.close()
  return value?.key
}

export async function deleteKey(id: string): Promise<void> {
  const db = await openOfflineDb()
  const transaction = db.transaction('keys', 'readwrite')
  transaction.objectStore('keys').delete(id)
  await transactionDone(transaction)
  db.close()
}

export async function putChunk(value: OfflineChunk): Promise<void> {
  const db = await openOfflineDb()
  const transaction = db.transaction('chunks', 'readwrite')
  transaction.objectStore('chunks').put(value)
  await transactionDone(transaction)
  db.close()
}

export async function getChunks(packageId: string): Promise<OfflineChunk[]> {
  const db = await openOfflineDb()
  const values = await requestResult(db.transaction('chunks').objectStore('chunks').index('packageId').getAll(packageId)) as OfflineChunk[]
  db.close()
  return values
}

export async function deleteChunks(packageId: string): Promise<OfflineChunk[]> {
  const chunks = await getChunks(packageId)
  const db = await openOfflineDb()
  const transaction = db.transaction('chunks', 'readwrite')
  const store = transaction.objectStore('chunks')
  chunks.forEach((chunk) => { store.delete(chunk.id) })
  await transactionDone(transaction)
  db.close()
  return chunks
}
