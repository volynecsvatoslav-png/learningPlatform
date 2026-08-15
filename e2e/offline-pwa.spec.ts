import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { expect, test } from '@playwright/test'
import licenseFixture from '../apps/api/learner/tests/fixtures/offline_license.json'

const video = readFileSync(resolve('e2e/fixtures/offline-test.mp4'))
const videoSha256 = createHash('sha256').update(video).digest('hex')
const snapshot = {
  title: 'Offline PWA course',
  short_description: 'Encrypted offline fixture',
  description_markdown: '',
  viewer: { email: 'learner@example.com', session_id: 'session-1' },
  modules: [{ id: 'module-1', title: 'Module', description: '', lessons: [{
    id: 'lesson-1', title: 'Video lesson', description: '', content_units: [{
      id: 'unit-1', type: 'video', title: 'Offline video', position: 1,
      text_markdown: null, media_asset_id: 'asset-1', is_downloadable: true,
    }],
  }] }],
}

test('downloads, plays, expires and deletes an encrypted PWA course', async ({ context, page }) => {
  await context.route('**/api/v1/learner/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (url.pathname === '/api/v1/learner/csrf') {
      await route.fulfill({ json: { csrfToken: 'e2e-csrf' } })
      return
    }
    if (url.pathname === '/api/v1/learner/courses') {
      await route.fulfill({ json: [{ id: 'course-1', title: snapshot.title, short_description: snapshot.short_description, description_markdown: '', cover_asset_id: null }] })
      return
    }
    if (url.pathname === '/api/v1/learner/courses/course-1') {
      await route.fulfill({ json: snapshot })
      return
    }
    if (url.pathname.includes('/progress')) {
      await route.fulfill({ json: [] })
      return
    }
    if (url.pathname.endsWith('/offline-manifest')) {
      await route.fulfill({ json: {
        course_id: 'course-1', revision_id: 'revision-1', revision: 1, snapshot,
        assets: [{ id: 'asset-1', content_type: 'video/mp4', size_bytes: video.byteLength, sha256: videoSha256, chunk_size: 4 * 1024 * 1024, chunk_count: 1 }],
        total_size: video.byteLength,
      } })
      return
    }
    if (url.pathname.endsWith('/offline-license')) {
      await route.fulfill({ json: {
        token: licenseFixture.tokens['revision-1'],
        claims: { ...licenseFixture.claims, revision_id: 'revision-1', revision: 1 },
        current_revision_id: 'revision-1', current_revision: 1, update_available: false,
      } })
      return
    }
    if (url.pathname.includes('/offline-media/')) {
      const match = /^bytes=(\d+)-(\d+)$/.exec(request.headers().range ?? '')
      const start = Number(match?.[1] ?? 0)
      const end = Number(match?.[2] ?? video.byteLength - 1)
      await route.fulfill({
        status: 206,
        body: video.subarray(start, end + 1),
        headers: {
          'Accept-Ranges': 'bytes',
          'Content-Length': String(end - start + 1),
          'Content-Range': `bytes ${String(start)}-${String(end)}/${String(video.byteLength)}`,
          'Content-Type': 'video/mp4',
        },
      })
      return
    }
    if (url.pathname.endsWith('/stream-url')) {
      await route.fulfill({ json: { url: '/api/online-video' } })
      return
    }
    await route.fulfill({ status: 404, json: { code: 'NOT_FOUND' } })
  })
  await context.route('**/api/online-video', async (route) => {
    await route.fulfill({ body: video, headers: { 'Content-Type': 'video/mp4' } })
  })

  await page.goto('/app/')
  await page.evaluate(async () => { await navigator.serviceWorker.ready })
  await page.reload()
  await expect(page.getByText('Офлайн-функции готовы')).toBeVisible()
  await page.getByRole('button', { name: /Offline PWA course/i }).click()
  await page.getByRole('button', { name: 'Скачать курс' }).click()
  await expect(page.getByText('Доступно офлайн')).toBeVisible()

  await context.unrouteAll({ behavior: 'wait' })
  await context.setOffline(true)
  await page.reload()
  await page.getByRole('button', { name: /Offline PWA course/i }).click()
  const storedAssetIds = await page.evaluate(async () => {
    const db = await new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open('learning-platform-offline', 1)
      request.onsuccess = () => { resolve(request.result) }
      request.onerror = () => { reject(request.error) }
    })
    const packageRecord = await new Promise<{ assets: Array<{ id: string }> }>((resolve, reject) => {
      const request = db.transaction('packages').objectStore('packages').get('course-1')
      request.onsuccess = () => { resolve(request.result as { assets: Array<{ id: string }> }) }
      request.onerror = () => { reject(request.error) }
    })
    db.close()
    return packageRecord.assets.map((asset) => asset.id)
  })
  expect(storedAssetIds).toContain('asset-1')
  const media = page.locator('video')
  await expect(media).toHaveAttribute('src', '/offline-media/course-1/asset-1')
  const rangeResult = await page.evaluate(async () => {
    const response = await fetch('/offline-media/course-1/asset-1', { headers: { Range: 'bytes=0-127' } })
    return { status: response.status, range: response.headers.get('Content-Range'), size: (await response.arrayBuffer()).byteLength }
  })
  expect(rangeResult).toEqual({ status: 206, range: `bytes 0-127/${String(video.byteLength)}`, size: 128 })
  await media.evaluate(async (element: HTMLVideoElement) => { element.muted = true; await element.play(); element.currentTime = 1 })
  await expect.poll(() => media.evaluate((element: HTMLVideoElement) => element.currentTime)).toBeGreaterThan(0)
  expect(await page.content()).not.toContain('object_key')
  expect(await page.content()).not.toContain('s3')

  await page.evaluate(async (expiredToken) => {
    const db = await new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open('learning-platform-offline', 1)
      request.onsuccess = () => { resolve(request.result) }
      request.onerror = () => { reject(request.error) }
    })
    const transaction = db.transaction('packages', 'readwrite')
    const store = transaction.objectStore('packages')
    const item = await new Promise<Record<string, unknown>>((resolve, reject) => {
      const request = store.get('course-1')
      request.onsuccess = () => { resolve(request.result as Record<string, unknown>) }
      request.onerror = () => { reject(request.error) }
    })
    store.put({ ...item, licenseToken: expiredToken })
    await new Promise<void>((resolve) => { transaction.oncomplete = () => { resolve() } })
    db.close()
  }, licenseFixture.tokens.expired)
  const expiredStatus = await page.evaluate(async () => (await fetch('/offline-media/course-1/asset-1', { headers: { Range: 'bytes=0-1' } })).status)
  expect(expiredStatus).toBe(403)

  await page.getByRole('button', { name: 'Удалить с устройства' }).click()
  const readStorageState = () => page.evaluate(async () => {
    const db = await new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open('learning-platform-offline', 1)
      request.onsuccess = () => { resolve(request.result) }
      request.onerror = () => { reject(request.error) }
    })
    const counts = await Promise.all(['packages', 'keys', 'chunks'].map((name) => new Promise<number>((resolve, reject) => {
      const request = db.transaction(name).objectStore(name).count()
      request.onsuccess = () => { resolve(request.result) }
      request.onerror = () => { reject(request.error) }
    })))
    db.close()
    const root = await navigator.storage.getDirectory()
    let opfsEntries = 0
    try {
      const directory = await root.getDirectoryHandle('learning-platform-offline')
      for await (const _entry of directory.values()) opfsEntries += 1
    } catch {
      opfsEntries = 0
    }
    return { counts, opfsEntries }
  })
  await expect.poll(readStorageState).toEqual({ counts: [0, 0, 0], opfsEntries: 0 })
})

test('purges legacy auth entries and never caches access URLs', async ({ context, page }) => {
  const legacySecret = 'legacy-secret-that-must-be-purged'
  await page.goto('/app/')
  await page.evaluate(async (secret) => {
    await navigator.serviceWorker.ready
    const cache = await caches.open('learning-platform-shell-v2')
    await cache.put(`/app/access/${secret}`, new Response('legacy sensitive entry'))
    const registration = await navigator.serviceWorker.getRegistration()
    await registration?.unregister()
  }, legacySecret)
  await page.close()

  const freshPage = await context.newPage()
  await freshPage.goto('/app/')
  await freshPage.evaluate(async () => { await navigator.serviceWorker.ready })
  await freshPage.reload()
  await expect.poll(() => freshPage.evaluate(async (secret) => {
    const names = await caches.keys()
    const urls = (await Promise.all(names.map(async (name) => (await caches.open(name)).keys()))).flat().map((request) => request.url)
    return urls.every((url) => !url.includes(secret))
  }, legacySecret)).toBe(true)

  const currentSecret = 'current-secret-that-must-not-be-cached'
  await freshPage.goto(`/app/access/${currentSecret}`)
  await expect(freshPage.getByRole('heading', { name: 'Персональный доступ' })).toBeVisible()
  const cachedUrls = await freshPage.evaluate(async () => {
    const names = await caches.keys()
    return (await Promise.all(names.map(async (name) => (await caches.open(name)).keys()))).flat().map((request) => request.url)
  })
  expect(cachedUrls.some((url) => url.includes(currentSecret))).toBe(false)
})
