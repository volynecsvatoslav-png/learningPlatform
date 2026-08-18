const CACHE_PREFIX = 'learning-platform-shell-'
const SHELL_CACHE = `${CACHE_PREFIX}v3`
const DB_NAME = 'learning-platform-offline'
const DB_VERSION = 1
const encoder = new TextEncoder()
const configuredLicenseKey = new URL(self.location.href).searchParams.get('licenseKey')
const OFFLINE_LICENSE_PUBLIC_JWK = configuredLicenseKey ? JSON.parse(configuredLicenseKey) : null

function isSensitivePath(pathname) {
  return /^\/app\/access(?:\/|$)/.test(pathname)
    || /^\/vendor\/reset(?:\/|$)/.test(pathname)
    || /^\/api\/v1\/learner\/(?:access|csrf|session|logout|pwa-transfer)(?:\/|$)/.test(pathname)
    || /^\/api\/v1\/auth\/(?:access|recovery|me|heartbeat|logout)(?:\/|$)/.test(pathname)
    || /^\/api\/v1\/vendor\/(?:csrf|auth)(?:\/|$)/.test(pathname)
}

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(SHELL_CACHE).then((cache) => cache.add('/app/')).then(() => self.skipWaiting()))
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((names) => Promise.all(names.filter((name) => name.startsWith(CACHE_PREFIX)).map(async (name) => {
        const cache = await caches.open(name)
        const requests = await cache.keys()
        await Promise.all(requests.filter((request) => isSensitivePath(new URL(request.url).pathname)).map((request) => cache.delete(request)))
        if (name !== SHELL_CACHE) await caches.delete(name)
      })))
      .then(() => self.clients.claim()),
  )
})

function openDb() {
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
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}

async function getRecord(storeName, id) {
  const db = await openDb()
  try {
    return await new Promise((resolve, reject) => {
      const request = db.transaction(storeName).objectStore(storeName).get(id)
      request.onsuccess = () => resolve(request.result)
      request.onerror = () => reject(request.error)
    })
  } finally {
    db.close()
  }
}

function decodeBase64Url(value) {
  const normalized = value.replace(/-/g, '+').replace(/_/g, '/')
  const binary = atob(normalized.padEnd(Math.ceil(normalized.length / 4) * 4, '='))
  return Uint8Array.from(binary, (character) => character.charCodeAt(0))
}

async function verifyLicense(offlinePackage) {
  const parts = offlinePackage.licenseToken.split('.')
  if (parts.length !== 3) throw new Error('OFFLINE_LICENSE_INVALID')
  if (!OFFLINE_LICENSE_PUBLIC_JWK) throw new Error('OFFLINE_LICENSE_INVALID')
  const header = JSON.parse(new TextDecoder().decode(decodeBase64Url(parts[0])))
  if (header.alg !== 'ES256') throw new Error('OFFLINE_LICENSE_INVALID')
  const key = await crypto.subtle.importKey('jwk', OFFLINE_LICENSE_PUBLIC_JWK, { name: 'ECDSA', namedCurve: 'P-256' }, false, ['verify'])
  const valid = await crypto.subtle.verify(
    { name: 'ECDSA', hash: 'SHA-256' },
    key,
    decodeBase64Url(parts[2]),
    encoder.encode(`${parts[0]}.${parts[1]}`),
  )
  if (!valid) throw new Error('OFFLINE_LICENSE_INVALID')
  const claims = JSON.parse(new TextDecoder().decode(decodeBase64Url(parts[1])))
  if (!Number.isSafeInteger(claims.iat) || claims.iat * 1000 > Date.now() + 5 * 60 * 1000) throw new Error('OFFLINE_LICENSE_INVALID')
  if (claims.expires_at * 1000 <= Date.now()) throw new Error('OFFLINE_LICENSE_EXPIRED')
  if (claims.exp !== claims.expires_at || claims.issued_at !== claims.iat) throw new Error('OFFLINE_LICENSE_INVALID')
  if (claims.course_id !== offlinePackage.courseId || claims.revision_id !== offlinePackage.revisionId || claims.learner_id !== offlinePackage.learnerId || claims.device_id !== offlinePackage.deviceId || claims.access_pass_id !== offlinePackage.accessPassId || claims.pass_generation !== offlinePackage.passGeneration) throw new Error('OFFLINE_LICENSE_INVALID')
  return claims
}

function parseRange(value, size) {
  if (!value) return { start: 0, end: size - 1, partial: false }
  const match = /^bytes=(\d*)-(\d*)$/.exec(value)
  if (!match || (!match[1] && !match[2])) return null
  if (!match[1]) {
    const length = Number(match[2])
    if (!Number.isSafeInteger(length) || length <= 0) return null
    return { start: Math.max(0, size - length), end: size - 1, partial: true }
  }
  const start = Number(match[1])
  const end = match[2] ? Number(match[2]) : size - 1
  if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start >= size || end < start) return null
  return { start, end: Math.min(end, size - 1), partial: true }
}

function chunkAad(courseId, revisionId, assetId, index) {
  return encoder.encode(`${courseId}:${revisionId}:${assetId}:${String(index)}`)
}

async function readOpfsCiphertext(path) {
  const [directoryName, fileName] = path.split('/')
  const root = await navigator.storage.getDirectory()
  const base = await root.getDirectoryHandle('learning-platform-offline')
  const directory = await base.getDirectoryHandle(directoryName)
  const file = await (await directory.getFileHandle(fileName)).getFile()
  return file.arrayBuffer()
}

async function decryptStoredChunk(offlinePackage, key, assetId, index) {
  const id = `${offlinePackage.packageId}:${assetId}:${String(index)}`
  const chunk = await getRecord('chunks', id)
  if (!chunk) throw new Error('OFFLINE_CHUNK_MISSING')
  const ciphertext = chunk.opfsPath ? await readOpfsCiphertext(chunk.opfsPath) : chunk.ciphertext
  if (!ciphertext) throw new Error('OFFLINE_CHUNK_MISSING')
  return crypto.subtle.decrypt(
    { name: 'AES-GCM', iv: chunk.iv, additionalData: chunkAad(offlinePackage.courseId, offlinePackage.revisionId, assetId, index) },
    key,
    ciphertext,
  )
}

async function offlineMediaResponse(request, courseId, assetId) {
  const offlinePackage = await getRecord('packages', courseId)
  if (!offlinePackage || offlinePackage.status !== 'ready') return new Response('Offline media not found', { status: 404 })
  try {
    await verifyLicense(offlinePackage)
  } catch (error) {
    return new Response(error instanceof Error ? error.message : 'OFFLINE_LICENSE_INVALID', { status: 403 })
  }
  const keyRecord = await getRecord('keys', offlinePackage.packageId)
  const asset = offlinePackage.assets.find((item) => item.id === assetId)
  if (!keyRecord?.key || !asset) return new Response('Offline media not found', { status: 404 })
  const range = parseRange(request.headers.get('Range'), asset.size_bytes)
  if (!range) {
    return new Response(null, {
      status: 416,
      headers: { 'Content-Range': `bytes */${String(asset.size_bytes)}`, 'Accept-Ranges': 'bytes' },
    })
  }
  const firstChunk = Math.floor(range.start / asset.chunk_size)
  const lastChunk = Math.floor(range.end / asset.chunk_size)
  const body = new ReadableStream({
    async start(controller) {
      try {
        for (let index = firstChunk; index <= lastChunk; index += 1) {
          const plain = new Uint8Array(await decryptStoredChunk(offlinePackage, keyRecord.key, assetId, index))
          const chunkStart = index * asset.chunk_size
          const from = Math.max(0, range.start - chunkStart)
          const to = Math.min(plain.byteLength, range.end - chunkStart + 1)
          controller.enqueue(plain.slice(from, to))
        }
        controller.close()
      } catch (error) {
        controller.error(error)
      }
    },
  })
  const headers = {
    'Accept-Ranges': 'bytes',
    'Cache-Control': 'private, no-store',
    'Content-Disposition': 'inline',
    'Content-Length': String(range.end - range.start + 1),
    'Content-Type': asset.content_type,
  }
  if (range.partial) headers['Content-Range'] = `bytes ${String(range.start)}-${String(range.end)}/${String(asset.size_bytes)}`
  return new Response(body, { status: range.partial ? 206 : 200, headers })
}

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url)
  const offlineMatch = /^\/offline-media\/([^/]+)\/([^/]+)$/.exec(url.pathname)
  if (offlineMatch) {
    event.respondWith(offlineMediaResponse(event.request, decodeURIComponent(offlineMatch[1]), decodeURIComponent(offlineMatch[2])))
    return
  }
  if (url.origin === self.location.origin && isSensitivePath(url.pathname)) {
    if (url.pathname.startsWith('/api/')) return
    event.respondWith(fetch(event.request, { cache: 'no-store' }))
    return
  }
  if (event.request.method !== 'GET' || url.origin !== self.location.origin || url.pathname.startsWith('/api/')) return
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (response.ok && !response.headers.get('Cache-Control')?.includes('no-store')) void caches.open(SHELL_CACHE).then((cache) => cache.put(event.request, response.clone()))
        return response
      })
      .catch(async () => (await caches.match(event.request)) ?? (event.request.mode === 'navigate' ? (await caches.match('/app/')) ?? Response.error() : Response.error())),
  )
})
