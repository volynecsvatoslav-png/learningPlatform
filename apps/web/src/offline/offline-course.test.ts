import { ApiError, learnerApi, type LearnerSnapshot } from '../lib/api'
import fixture from '../../../api/learner/tests/fixtures/offline_license.json'
import { createOfflineKey, decodeLicenseClaims, decryptChunk, encryptChunk, verifyOfflineLicense } from './crypto'
import { getChunks, getKey } from './db'
import { downloadOfflineCourse, getOfflinePackage, offlineMediaUrl, readOfflineSnapshot, syncOfflineCourse } from './offline-course'
import { OFFLINE_LICENSE_PUBLIC_JWK } from './license-key'
import type { OfflineLicense, OfflineManifest } from './types'

const deviceStub = vi.hoisted(() => ({
  installation_id: 'device-1',
  public_key_jwk: { kty: 'EC', crv: 'P-256', x: 'x-coordinate', y: 'y-coordinate' },
  sign: (message: string) => Promise.resolve(`signature:${message}`),
}))
vi.mock('../lib/device-keys', () => ({
  getAccessDevice: () => Promise.resolve(deviceStub),
  sha256Hex: (value: string) => Promise.resolve(value),
}))

const snapshot: LearnerSnapshot = {
  title: 'Offline course',
  short_description: 'Stored privately',
  description_markdown: '',
  viewer: { email: 'learner@example.com', session_id: 'session1' },
  modules: [{ id: 'module-1', title: 'Module', description: '', lessons: [{
    id: 'lesson-1',
    title: 'Lesson',
    description: '',
    content_units: [{ id: 'unit-1', type: 'video', title: 'Video', position: 1, text_markdown: null, media_asset_id: 'asset-1', is_downloadable: true }],
  }] }],
}

function signedLicense(revisionId: 'revision-1' | 'revision-2'): OfflineLicense {
  const token = fixture.tokens[revisionId]
  const claims = decodeLicenseClaims(token)
  return {
    token,
    claims,
    current_revision_id: revisionId,
    current_revision: claims.revision,
    update_available: false,
  }
}

function manifest(revisionId = 'revision-1'): OfflineManifest {
  return {
    course_id: 'course-1',
    revision_id: revisionId,
    revision: revisionId === 'revision-1' ? 1 : 2,
    snapshot,
    assets: [{ id: 'asset-1', content_type: 'video/mp4', size_bytes: 6, sha256: '7192385c3c0605de55bb9476ce1d90748190ecb32a8eed7f5207b30cf6a1fe89', chunk_size: 4, chunk_count: 2 }],
    total_size: 6,
  }
}

async function deleteOfflineDatabase(): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    const request = indexedDB.deleteDatabase('learning-platform-offline')
    request.onsuccess = () => { resolve() }
    request.onerror = () => { reject(request.error ?? new Error('INDEXED_DB_ERROR')) }
  })
}

function chunkFetch(source: Uint8Array): typeof fetch {
  return vi.fn<typeof fetch>((_input, init) => {
    const headers = init?.headers as Record<string, string> | undefined
    const match = /bytes=(\d+)-(\d+)/.exec(headers?.Range ?? '')
    const start = Number(match?.[1] ?? 0)
    const end = Number(match?.[2] ?? source.length - 1)
    return Promise.resolve(new Response(source.slice(start, end + 1), { status: 206 }))
  })
}

describe('offline course storage', () => {
  beforeEach(async () => {
    await deleteOfflineDatabase()
    vi.restoreAllMocks()
    Object.defineProperty(navigator, 'storage', {
      configurable: true,
      value: { estimate: vi.fn().mockResolvedValue({ quota: 1024 * 1024, usage: 0 }), persist: vi.fn().mockResolvedValue(true) },
    })
  })

  afterEach(async () => {
    await deleteOfflineDatabase()
    vi.unstubAllGlobals()
  })

  it('uses non-extractable browser keys and rejects another key or a damaged chunk', async () => {
    const first = await createOfflineKey()
    const second = await createOfflineKey()
    expect(first.extractable).toBe(false)
    const aad = new TextEncoder().encode('course:revision:asset:0')
    const encrypted = await encryptChunk(first, new TextEncoder().encode('private video chunk'), aad)

    await expect(decryptChunk(second, encrypted.ciphertext, encrypted.iv, aad)).rejects.toBeInstanceOf(Error)
    const damaged = new Uint8Array(encrypted.ciphertext)
    damaged[0] = (damaged[0] ?? 0) ^ 1
    await expect(decryptChunk(first, damaged, encrypted.iv, aad)).rejects.toBeInstanceOf(Error)
  })

  it('rejects an expired signed offline license', async () => {
    await expect(verifyOfflineLicense(fixture.tokens.expired, { courseId: 'course-1', revisionId: 'revision-1' })).rejects.toThrow('OFFLINE_LICENSE_EXPIRED')
  })

  it('verifies the Django ES256 fixture with the pinned WebCrypto key', async () => {
    expect(OFFLINE_LICENSE_PUBLIC_JWK).toMatchObject(fixture.publicJwk)
    await expect(verifyOfflineLicense(fixture.tokens['revision-1'], { courseId: 'course-1', revisionId: 'revision-1', learnerId: 'learner-1', deviceId: 'device-1', accessPassId: 'pass-1', passGeneration: 1 })).resolves.toMatchObject({ learner_id: 'learner-1', device_id: 'device-1', access_pass_id: 'pass-1', pass_generation: 1 })
  })

  it('reports insufficient private storage before downloading media', async () => {
    Object.defineProperty(navigator, 'storage', {
      configurable: true,
      value: { estimate: vi.fn().mockResolvedValue({ quota: 5, usage: 0 }), persist: vi.fn() },
    })
    vi.spyOn(learnerApi, 'offlineManifest').mockResolvedValue(manifest())

    await expect(downloadOfflineCourse('course-1', () => undefined, new AbortController().signal)).rejects.toMatchObject({ code: 'QUOTA_EXCEEDED' })
  })

  it('downloads encrypted chunks with progress and reads the course without network', async () => {
    vi.spyOn(learnerApi, 'offlineManifest').mockResolvedValue(manifest())
    vi.spyOn(learnerApi, 'offlineLicense').mockResolvedValue(signedLicense('revision-1'))
    const source = new Uint8Array([1, 2, 3, 4, 5, 6])
    vi.stubGlobal('fetch', chunkFetch(source))
    const progress: Array<[number, number]> = []

    const result = await downloadOfflineCourse('course-1', (loaded, total) => { progress.push([loaded, total]) }, new AbortController().signal)

    expect(result.assets[0]?.id).toBe('asset-1')
    expect(progress).toEqual([[0, 6], [4, 6], [6, 6]])
    expect(await readOfflineSnapshot('course-1')).toMatchObject({ title: 'Offline course' })
    expect(offlineMediaUrl('course-1', 'asset-1')).toBe('/offline-media/course-1/asset-1')
    expect(JSON.stringify(result)).not.toContain('object_key')
    expect(JSON.stringify(result)).not.toContain('s3')
  })

  it('rejects equal-sized media with a mismatched SHA-256 and preserves a ready package', async () => {
    vi.spyOn(learnerApi, 'offlineManifest').mockResolvedValue(manifest())
    vi.spyOn(learnerApi, 'offlineLicense').mockResolvedValue(signedLicense('revision-1'))
    vi.stubGlobal('fetch', chunkFetch(new Uint8Array([1, 2, 3, 4, 5, 6])))
    const ready = await downloadOfflineCourse('course-1', () => undefined, new AbortController().signal)
    vi.stubGlobal('fetch', chunkFetch(new Uint8Array([6, 5, 4, 3, 2, 1])))

    await expect(downloadOfflineCourse('course-1', () => undefined, new AbortController().signal)).rejects.toMatchObject({ code: 'OFFLINE_CHECKSUM_MISMATCH' })
    expect((await getOfflinePackage('course-1'))?.packageId).toBe(ready.packageId)
    expect(await getKey(ready.packageId)).toBeDefined()
  })

  it('stores text-only snapshots without media chunks', async () => {
    const textManifest = { ...manifest(), assets: [], total_size: 0, snapshot: { ...snapshot, modules: [{ id: 'module-1', title: 'Module', description: '', lessons: [{ id: 'lesson-1', title: 'Text', description: '', content_units: [{ id: 'text-1', type: 'text' as const, title: '', position: 1, text_markdown: '# Offline', media_asset_id: null, is_downloadable: false }] }] }] } }
    vi.spyOn(learnerApi, 'offlineManifest').mockResolvedValue(textManifest)
    vi.spyOn(learnerApi, 'offlineLicense').mockResolvedValue(signedLicense('revision-1'))

    const result = await downloadOfflineCourse('course-1', () => undefined, new AbortController().signal)

    expect(result.assets).toEqual([])
    expect(await readOfflineSnapshot('course-1')).toMatchObject({ title: 'Offline course' })
  })

  it('falls back per chunk to IndexedDB when OPFS writing fails', async () => {
    const file = { createWritable: vi.fn().mockRejectedValue(new Error('OPFS write failed')) }
    const directory = { getFileHandle: vi.fn().mockResolvedValue(file) }
    const base = { getDirectoryHandle: vi.fn().mockResolvedValue(directory) }
    const root = { getDirectoryHandle: vi.fn().mockResolvedValue(base) }
    Object.defineProperty(navigator, 'storage', { configurable: true, value: { estimate: vi.fn().mockResolvedValue({ quota: 1024 * 1024, usage: 0 }), persist: vi.fn(), getDirectory: vi.fn().mockResolvedValue(root) } })
    vi.spyOn(learnerApi, 'offlineManifest').mockResolvedValue(manifest())
    vi.spyOn(learnerApi, 'offlineLicense').mockResolvedValue(signedLicense('revision-1'))
    vi.stubGlobal('fetch', chunkFetch(new Uint8Array([1, 2, 3, 4, 5, 6])))

    const result = await downloadOfflineCourse('course-1', () => undefined, new AbortController().signal)
    const chunks = await getChunks(result.packageId)

    expect(result.storageKind).toBe('mixed')
    expect(chunks.every((chunk) => Boolean(chunk.ciphertext?.byteLength) && !chunk.opfsPath)).toBe(true)
  })

  it('removes content and its local key when access is revoked during sync', async () => {
    vi.spyOn(learnerApi, 'offlineManifest').mockResolvedValue(manifest())
    vi.spyOn(learnerApi, 'offlineLicense').mockResolvedValue(signedLicense('revision-1'))
    vi.stubGlobal('fetch', chunkFetch(new Uint8Array([1, 2, 3, 4, 5, 6])))
    const downloaded = await downloadOfflineCourse('course-1', () => undefined, new AbortController().signal)
    vi.spyOn(learnerApi, 'offlineLicense').mockRejectedValue(new ApiError(404, 'ACCESS_REVOKED'))

    await expect(syncOfflineCourse('course-1')).rejects.toMatchObject({ status: 404 })
    expect(await getOfflinePackage('course-1')).toBeUndefined()
    expect(await getKey(downloaded.packageId)).toBeUndefined()
  })

  it('keeps the package when the session was replaced during sync', async () => {
    vi.spyOn(learnerApi, 'offlineManifest').mockResolvedValue(manifest())
    vi.spyOn(learnerApi, 'offlineLicense').mockResolvedValue(signedLicense('revision-1'))
    vi.stubGlobal('fetch', chunkFetch(new Uint8Array([1, 2, 3, 4, 5, 6])))
    const downloaded = await downloadOfflineCourse('course-1', () => undefined, new AbortController().signal)
    vi.spyOn(learnerApi, 'offlineLicense').mockRejectedValue(new ApiError(401, 'SESSION_REPLACED'))

    await expect(syncOfflineCourse('course-1')).rejects.toMatchObject({ status: 401 })
    expect(await getOfflinePackage('course-1')).toBeDefined()
    expect(await getKey(downloaded.packageId)).toBeDefined()
  })

  it('keeps the old revision until a complete update replaces it', async () => {
    const manifestSpy = vi.spyOn(learnerApi, 'offlineManifest').mockResolvedValue(manifest())
    const licenseSpy = vi.spyOn(learnerApi, 'offlineLicense').mockResolvedValue(signedLicense('revision-1'))
    vi.stubGlobal('fetch', chunkFetch(new Uint8Array([1, 2, 3, 4, 5, 6])))
    const first = await downloadOfflineCourse('course-1', () => undefined, new AbortController().signal)
    licenseSpy.mockRejectedValue(new ApiError(409, 'OFFLINE_REVISION_OUTDATED', { code: 'OFFLINE_REVISION_OUTDATED', current_revision_id: 'revision-2', offline_available: true }))
    const update = await syncOfflineCourse('course-1')
    expect(update?.revisionId).toBe('revision-1')
    expect(update?.updateAvailable).toBe(true)

    manifestSpy.mockResolvedValue(manifest('revision-2'))
    licenseSpy.mockResolvedValue(signedLicense('revision-2'))
    const second = await downloadOfflineCourse('course-1', () => undefined, new AbortController().signal)
    expect(second.revisionId).toBe('revision-2')
    expect(await getKey(first.packageId)).toBeUndefined()
    expect(await getKey(second.packageId)).toBeDefined()
  })

  it('deletes an outdated package when the current revision has no offline content', async () => {
    vi.spyOn(learnerApi, 'offlineManifest').mockResolvedValue(manifest())
    const licenseSpy = vi.spyOn(learnerApi, 'offlineLicense').mockResolvedValue(signedLicense('revision-1'))
    vi.stubGlobal('fetch', chunkFetch(new Uint8Array([1, 2, 3, 4, 5, 6])))
    await downloadOfflineCourse('course-1', () => undefined, new AbortController().signal)
    licenseSpy.mockRejectedValue(new ApiError(409, 'OFFLINE_REVISION_OUTDATED', { code: 'OFFLINE_REVISION_OUTDATED', current_revision_id: 'revision-2', offline_available: false }))

    await expect(syncOfflineCourse('course-1')).resolves.toBeUndefined()
    expect(await getOfflinePackage('course-1')).toBeUndefined()
  })
})
