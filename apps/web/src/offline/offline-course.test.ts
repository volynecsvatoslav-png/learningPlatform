import { ApiError, learnerApi, type LearnerSnapshot } from '../lib/api'
import { createOfflineKey, decryptChunk, encryptChunk, verifyOfflineLicense } from './crypto'
import { getKey } from './db'
import { downloadOfflineCourse, getOfflinePackage, offlineMediaUrl, readOfflineSnapshot, syncOfflineCourse } from './offline-course'
import type { OfflineLicense, OfflineLicenseClaims, OfflineManifest } from './types'

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

function base64Url(value: Uint8Array): string {
  let binary = ''
  value.forEach((byte) => { binary += String.fromCharCode(byte) })
  return btoa(binary).replace(/=/g, '').replace(/\+/g, '-').replace(/\//g, '_')
}

async function signedLicense(revisionId: string, options: { expired?: boolean; updateAvailable?: boolean; currentRevisionId?: string } = {}): Promise<OfflineLicense> {
  const keys = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify'])
  const now = Math.floor(Date.now() / 1000)
  const claims: OfflineLicenseClaims = {
    license_id: 'license-1',
    learner_id: 'learner-1',
    course_id: 'course-1',
    revision_id: revisionId,
    revision: revisionId === 'revision-1' ? 1 : 2,
    device_id: 'device-1',
    session_id: 'session-1',
    issued_at: now,
    expires_at: options.expired ? now - 1 : now + 604800,
    iat: now,
    exp: options.expired ? now - 1 : now + 604800,
  }
  const header = base64Url(new TextEncoder().encode(JSON.stringify({ alg: 'ES256', typ: 'JWT' })))
  const payload = base64Url(new TextEncoder().encode(JSON.stringify(claims)))
  const signature = new Uint8Array(await crypto.subtle.sign({ name: 'ECDSA', hash: 'SHA-256' }, keys.privateKey, new TextEncoder().encode(`${header}.${payload}`)))
  const token = `${header}.${payload}.${base64Url(signature)}`
  return {
    token,
    claims,
    verification_key: await crypto.subtle.exportKey('jwk', keys.publicKey),
    current_revision_id: options.currentRevisionId ?? revisionId,
    current_revision: options.currentRevisionId === 'revision-2' ? 2 : claims.revision,
    update_available: options.updateAvailable ?? false,
  }
}

function manifest(revisionId = 'revision-1'): OfflineManifest {
  return {
    course_id: 'course-1',
    revision_id: revisionId,
    revision: revisionId === 'revision-1' ? 1 : 2,
    snapshot,
    assets: [{ id: 'asset-1', content_type: 'video/mp4', size_bytes: 6, sha256: '0'.repeat(64), chunk_size: 4, chunk_count: 2 }],
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
    const license = await signedLicense('revision-1', { expired: true })
    await expect(verifyOfflineLicense(license.token, license.verification_key)).rejects.toThrow('OFFLINE_LICENSE_EXPIRED')
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
    vi.spyOn(learnerApi, 'offlineLicense').mockResolvedValue(await signedLicense('revision-1'))
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

  it('removes content and its local key when access is revoked during sync', async () => {
    vi.spyOn(learnerApi, 'offlineManifest').mockResolvedValue(manifest())
    vi.spyOn(learnerApi, 'offlineLicense').mockResolvedValue(await signedLicense('revision-1'))
    vi.stubGlobal('fetch', chunkFetch(new Uint8Array([1, 2, 3, 4, 5, 6])))
    const downloaded = await downloadOfflineCourse('course-1', () => undefined, new AbortController().signal)
    vi.spyOn(learnerApi, 'offlineLicense').mockRejectedValue(new ApiError(404, 'ACCESS_REVOKED'))

    await expect(syncOfflineCourse('course-1')).rejects.toMatchObject({ status: 404 })
    expect(await getOfflinePackage('course-1')).toBeUndefined()
    expect(await getKey(downloaded.packageId)).toBeUndefined()
  })

  it('keeps the old revision until a complete update replaces it', async () => {
    const manifestSpy = vi.spyOn(learnerApi, 'offlineManifest').mockResolvedValue(manifest())
    const licenseSpy = vi.spyOn(learnerApi, 'offlineLicense').mockResolvedValue(await signedLicense('revision-1'))
    vi.stubGlobal('fetch', chunkFetch(new Uint8Array([1, 2, 3, 4, 5, 6])))
    const first = await downloadOfflineCourse('course-1', () => undefined, new AbortController().signal)
    licenseSpy.mockResolvedValue(await signedLicense('revision-1', { updateAvailable: true, currentRevisionId: 'revision-2' }))
    const update = await syncOfflineCourse('course-1')
    expect(update?.revisionId).toBe('revision-1')
    expect(update?.updateAvailable).toBe(true)

    manifestSpy.mockResolvedValue(manifest('revision-2'))
    licenseSpy.mockResolvedValue(await signedLicense('revision-2'))
    const second = await downloadOfflineCourse('course-1', () => undefined, new AbortController().signal)
    expect(second.revisionId).toBe('revision-2')
    expect(await getKey(first.packageId)).toBeUndefined()
    expect(await getKey(second.packageId)).toBeDefined()
  })
})
