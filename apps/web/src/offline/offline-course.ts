import { ApiError, learnerApi, type LearnerCourse, type LearnerSnapshot } from '../lib/api'
import { getAccessDevice } from '../lib/device-keys'
import { createSHA256 } from 'hash-wasm'
import { chunkAad, createOfflineKey, decryptChunk, encryptChunk, verifyOfflineLicense } from './crypto'
import { deleteChunks, deleteKey, deletePackageRecord, getKey, getPackage, getPackages, putChunk, putKey, putPackage } from './db'
import type { OfflineLicense, OfflineManifest, OfflinePackage } from './types'

const encoder = new TextEncoder()

type StorageManagerWithDirectory = StorageManager & { getDirectory?: () => Promise<FileSystemDirectoryHandle> }

export class OfflineDownloadError extends Error {
  code: string
  constructor(code: string, message: string) {
    super(message)
    this.code = code
  }
}

function opfsDirectoryName(packageId: string): string {
  return packageId.replaceAll(':', '-')
}

async function getOpfsRoot(): Promise<FileSystemDirectoryHandle | null> {
  const storage = navigator.storage as StorageManagerWithDirectory | undefined
  if (!storage?.getDirectory) return null
  return storage.getDirectory()
}

async function writeOpfsChunk(packageId: string, name: string, ciphertext: ArrayBuffer): Promise<string> {
  const root = await getOpfsRoot()
  if (!root) throw new Error('OPFS_UNAVAILABLE')
  const base = await root.getDirectoryHandle('learning-platform-offline', { create: true })
  const directoryName = opfsDirectoryName(packageId)
  const directory = await base.getDirectoryHandle(directoryName, { create: true })
  const fileName = `${name}.chunk`
  const file = await directory.getFileHandle(fileName, { create: true })
  const writable = await file.createWritable()
  await writable.write(ciphertext)
  await writable.close()
  return `${directoryName}/${fileName}`
}

async function deleteOpfsPackage(packageId: string): Promise<void> {
  const root = await getOpfsRoot()
  if (!root) return
  try {
    const base = await root.getDirectoryHandle('learning-platform-offline')
    await base.removeEntry(opfsDirectoryName(packageId), { recursive: true })
  } catch {
    // The directory may not exist when IndexedDB fallback was used.
  }
}

async function deletePackageData(packageId: string): Promise<void> {
  await deleteChunks(packageId)
  await deleteKey(packageId)
  await deleteOpfsPackage(packageId)
}

async function ensureQuota(required: number): Promise<void> {
  const storage = navigator.storage as StorageManager | undefined
  if (!storage) return
  const estimate = await storage.estimate()
  if (estimate.quota === undefined) return
  const available = estimate.quota - (estimate.usage ?? 0)
  if (available < Math.ceil(required * 1.15)) {
    throw new OfflineDownloadError('QUOTA_EXCEEDED', `Недостаточно места. Требуется ${formatBytes(required)}, доступно ${formatBytes(Math.max(0, available))}.`)
  }
}

export function formatBytes(value: number): string {
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} КБ`
  if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} МБ`
  return `${(value / 1024 / 1024 / 1024).toFixed(2)} ГБ`
}

export async function downloadOfflineCourse(courseId: string, onProgress: (loaded: number, total: number) => void, signal: AbortSignal): Promise<OfflinePackage> {
  const manifest = await learnerApi.offlineManifest(courseId)
  await ensureQuota(manifest.total_size)
  const storage = navigator.storage as StorageManager | undefined
  if (storage) await storage.persist()
  const license = await learnerApi.offlineLicense(courseId, manifest.revision_id)
  const device = await getAccessDevice()
  const claims = await verifyOfflineLicense(license.token, { courseId, revisionId: manifest.revision_id, deviceId: device.installation_id })
  if (claims.course_id !== courseId || claims.revision_id !== manifest.revision_id) throw new OfflineDownloadError('OFFLINE_LICENSE_INVALID', 'Сервер вернул некорректную офлайн-лицензию.')

  const packageId = `${courseId}:${manifest.revision_id}:attempt:${crypto.randomUUID()}`
  const previous = await getPackage(courseId)
  const key = await createOfflineKey()
  await putKey(packageId, key)
  const snapshotEncrypted = await encryptChunk(key, encoder.encode(JSON.stringify(manifest.snapshot)), chunkAad(courseId, manifest.revision_id, 'snapshot', 0))
  let storageKind: OfflinePackage['storageKind'] = await getOpfsRoot() ? 'opfs' : 'idb'
  let loaded = 0
  onProgress(loaded, manifest.total_size)
  let committed = false
  try {
    for (const asset of manifest.assets) {
      const hasher = await createSHA256()
      hasher.init()
      for (let index = 0; index < asset.chunk_count; index += 1) {
        if (signal.aborted) throw new DOMException('Download aborted', 'AbortError')
        const start = index * asset.chunk_size
        const end = Math.min(asset.size_bytes - 1, start + asset.chunk_size - 1)
        const response = await fetch(`/api/v1/learner/courses/${encodeURIComponent(courseId)}/offline-media/${encodeURIComponent(manifest.revision_id)}/${encodeURIComponent(asset.id)}`, {
          credentials: 'include',
          headers: { Range: `bytes=${String(start)}-${String(end)}` },
          cache: 'no-store',
          signal,
        })
        if (!response.ok) throw new ApiError(response.status, 'OFFLINE_CHUNK_FAILED')
        const plain = await response.arrayBuffer()
        if (plain.byteLength !== end - start + 1) throw new OfflineDownloadError('OFFLINE_CHUNK_INVALID', 'Сервер вернул повреждённый блок медиа.')
        hasher.update(new Uint8Array(plain))
        const encrypted = await encryptChunk(key, plain, chunkAad(courseId, manifest.revision_id, asset.id, index))
        const id = `${packageId}:${asset.id}:${String(index)}`
        if (storageKind !== 'idb') {
          try {
            const opfsPath = await writeOpfsChunk(packageId, `${asset.id}-${String(index)}`, encrypted.ciphertext)
            await putChunk({ id, packageId, assetId: asset.id, index, iv: encrypted.iv, opfsPath })
          } catch {
            storageKind = 'mixed'
            await putChunk({ id, packageId, assetId: asset.id, index, iv: encrypted.iv, ciphertext: encrypted.ciphertext })
          }
        } else {
          await putChunk({ id, packageId, assetId: asset.id, index, iv: encrypted.iv, ciphertext: encrypted.ciphertext })
        }
        loaded += plain.byteLength
        onProgress(loaded, manifest.total_size)
      }
      if (hasher.digest('hex').toLowerCase() !== asset.sha256.toLowerCase()) {
        throw new OfflineDownloadError('OFFLINE_CHECKSUM_MISMATCH', 'Контрольная сумма медиа не совпала.')
      }
    }
    const offlinePackage: OfflinePackage = {
      courseId,
      packageId,
      revisionId: manifest.revision_id,
      revision: manifest.revision,
      title: manifest.snapshot.title,
      shortDescription: manifest.snapshot.short_description ?? '',
      licenseToken: license.token,
      licenseClaims: claims,
      learnerId: claims.learner_id,
      deviceId: claims.device_id,
      accessPassId: claims.access_pass_id,
      passGeneration: claims.pass_generation,
      snapshotIv: snapshotEncrypted.iv,
      snapshotCiphertext: snapshotEncrypted.ciphertext,
      assets: manifest.assets,
      totalSize: manifest.total_size,
      storageKind,
      status: 'ready',
      updateAvailable: false,
      createdAt: Date.now(),
    }
    await putPackage(offlinePackage)
    committed = true
    if (previous) await deletePackageData(previous.packageId).catch(() => undefined)
    return offlinePackage
  } catch (error) {
    if (!committed) await deletePackageData(packageId)
    throw error
  }
}

export async function readOfflineSnapshot(courseId: string): Promise<LearnerSnapshot | null> {
  const offlinePackage = await getPackage(courseId)
  if (!offlinePackage || offlinePackage.licenseClaims.expires_at * 1000 <= Date.now()) return null
  const key = await getKey(offlinePackage.packageId)
  if (!key) return null
  const plain = await decryptChunk(key, offlinePackage.snapshotCiphertext, offlinePackage.snapshotIv, chunkAad(courseId, offlinePackage.revisionId, 'snapshot', 0))
  return JSON.parse(new TextDecoder().decode(plain)) as LearnerSnapshot
}

export async function listOfflineCourses(): Promise<LearnerCourse[]> {
  const packages = await getPackages()
  return packages
    .filter((item) => item.licenseClaims.expires_at * 1000 > Date.now())
    .map((item) => ({ id: item.courseId, title: item.title, short_description: item.shortDescription, description_markdown: '', cover_asset_id: null }))
}

export async function deleteOfflineCourse(courseId: string): Promise<void> {
  const offlinePackage = await getPackage(courseId)
  if (!offlinePackage) return
  await deletePackageRecord(courseId)
  await deletePackageData(offlinePackage.packageId)
}

export async function deleteAllOfflineCourses(): Promise<void> {
  const packages = await getPackages()
  await Promise.all(packages.map((item) => deleteOfflineCourse(item.courseId)))
}

export async function syncOfflineCourse(courseId: string): Promise<OfflinePackage | undefined> {
  const offlinePackage = await getPackage(courseId)
  if (!offlinePackage) return undefined
  try {
    const license = await learnerApi.offlineLicense(courseId, offlinePackage.revisionId)
    const claims = await verifyOfflineLicense(license.token, {
      courseId,
      revisionId: offlinePackage.revisionId,
      learnerId: offlinePackage.learnerId,
      deviceId: offlinePackage.deviceId,
      accessPassId: offlinePackage.accessPassId,
      passGeneration: offlinePackage.passGeneration,
    })
    const updated = { ...offlinePackage, licenseToken: license.token, licenseClaims: claims, updateAvailable: false }
    await putPackage(updated)
    return updated
  } catch (error) {
    if (error instanceof ApiError && error.status === 409 && error.code === 'OFFLINE_REVISION_OUTDATED') {
      if (error.body.offline_available === false) {
        await deleteOfflineCourse(courseId)
        return undefined
      }
      const outdated = { ...offlinePackage, updateAvailable: true }
      await putPackage(outdated)
      return outdated
    }
    if (error instanceof ApiError && [401, 403, 404].includes(error.status) && error.code !== 'SESSION_REPLACED') await deleteOfflineCourse(courseId)
    throw error
  }
}

export async function getOfflinePackage(courseId: string): Promise<OfflinePackage | undefined> {
  return getPackage(courseId)
}

export async function syncOfflineCourses(): Promise<void> {
  const packages = await getPackages()
  await Promise.all(packages.map(async (item) => {
    try {
      await syncOfflineCourse(item.courseId)
    } catch {
      // A rejected package is purged by syncOfflineCourse; transient errors keep local data.
    }
  }))
}

export function offlineMediaUrl(courseId: string, assetId: string): string {
  return `/offline-media/${encodeURIComponent(courseId)}/${encodeURIComponent(assetId)}`
}

export type { OfflineLicense, OfflineManifest, OfflinePackage }
