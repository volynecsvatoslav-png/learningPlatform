import type { LearnerSnapshot } from '../lib/api'

export type OfflineAsset = {
  id: string
  content_type: string
  size_bytes: number
  sha256: string
  chunk_size: number
  chunk_count: number
}

export type OfflineManifest = {
  course_id: string
  revision_id: string
  revision: number
  snapshot: LearnerSnapshot
  assets: OfflineAsset[]
  total_size: number
}

export type OfflineLicenseClaims = {
  license_id: string
  learner_id: string
  course_id: string
  revision_id: string
  revision: number
  access_pass_id: string
  pass_generation: number
  device_id: string
  issued_at: number
  expires_at: number
  iat: number
  exp: number
}

export type OfflineLicense = {
  token: string
  claims: OfflineLicenseClaims
  current_revision_id: string
  current_revision: number
  update_available: boolean
}

export type OfflinePackage = {
  courseId: string
  packageId: string
  revisionId: string
  revision: number
  title: string
  shortDescription: string
  licenseToken: string
  licenseClaims: OfflineLicenseClaims
  learnerId: string
  deviceId: string
  accessPassId: string
  passGeneration: number
  snapshotIv: ArrayBuffer
  snapshotCiphertext: ArrayBuffer
  assets: OfflineAsset[]
  totalSize: number
  storageKind: 'opfs' | 'idb' | 'mixed'
  status: 'ready'
  updateAvailable: boolean
  createdAt: number
}

export type OfflineChunk = {
  id: string
  packageId: string
  assetId: string
  index: number
  iv: ArrayBuffer
  ciphertext?: ArrayBuffer
  opfsPath?: string
}
