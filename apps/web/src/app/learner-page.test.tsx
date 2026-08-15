import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { LearnerPage, MediaUnit } from './learner-page'
import type { OfflinePackage } from '../offline/types'

function renderPage(path = '/app/') {
  window.history.pushState({}, '', path)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}><LearnerPage /></QueryClientProvider>)
}

function response(data: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(data), { status }))
}

function requestUrl(input: RequestInfo | URL) {
  return typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
}

function setStandalone(value: boolean) {
  vi.stubGlobal('matchMedia', vi.fn(() => ({
    matches: value,
    media: '(display-mode: standalone)',
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(() => true),
  })))
  Object.defineProperty(navigator, 'standalone', { configurable: true, value })
}

const courses = [
  { id: 'course-1', title: 'First course', short_description: 'First route', description_markdown: '', cover_asset_id: null },
  { id: 'course-2', title: 'Second course', short_description: 'Second route', description_markdown: '', cover_asset_id: null },
]

const snapshot = {
  title: 'First course',
  description_markdown: '',
  viewer: { email: 'learner@example.com', session_id: 'abcd1234' },
  modules: [{ id: 'module-1', title: 'Module', description: '', lessons: [
    { id: 'lesson-1', title: 'Completed lesson', description: '', content_units: [] },
    { id: 'lesson-2', title: 'Older lesson', description: '', content_units: [] },
    { id: 'lesson-3', title: 'Recent lesson', description: '', content_units: [{ id: 'unit-1', type: 'text', title: '', position: 1, text_markdown: '# Continue here', media_asset_id: null }] },
  ] }],
}

describe('LearnerPage', () => {
  afterEach(async () => {
    vi.unstubAllGlobals()
    Object.defineProperty(navigator, 'standalone', { configurable: true, value: false })
    window.localStorage.clear()
    await new Promise<void>((resolve) => {
      const request = indexedDB.deleteDatabase('learning-platform-offline')
      request.onsuccess = () => { resolve() }
      request.onerror = () => { resolve() }
      request.onblocked = () => { resolve() }
    })
  })

  it('shows all courses separately and opens only the selected course', async () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>((input) => {
      const url = requestUrl(input)
      if (url.endsWith('/api/v1/learner/courses')) return response(courses)
      if (url.includes('/progress')) return response([])
      if (url.endsWith('/course-2')) return response({ ...snapshot, title: 'Second course' })
      return response(snapshot)
    }))
    renderPage()

    expect(await screen.findByRole('heading', { name: 'Все курсы' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /First course/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Second course/i })).toBeInTheDocument()
    expect(screen.queryByText('Completed lesson')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Second course/i }))
    expect(await screen.findByRole('heading', { name: 'Second course' })).toBeInTheDocument()
  })

  it('continues from the most recently updated in-progress lesson', async () => {
    const progress = [
      { lesson_id: 'lesson-1', percent: 100, status: 'completed', completed_at: '2026-01-01', updated_at: '2026-01-01T10:00:00Z' },
      { lesson_id: 'lesson-2', percent: 25, status: 'in_progress', completed_at: null, updated_at: '2026-02-01T10:00:00Z' },
      { lesson_id: 'lesson-3', percent: 50, status: 'in_progress', completed_at: null, updated_at: '2026-03-01T10:00:00Z' },
    ]
    vi.stubGlobal('fetch', vi.fn<typeof fetch>((input) => {
      const url = requestUrl(input)
      if (url.endsWith('/api/v1/learner/courses')) return response([courses[0]])
      if (url.includes('/progress')) return response(progress)
      return response(snapshot)
    }))
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /First course/i }))

    expect(await screen.findByRole('heading', { name: 'Recent lesson' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Continue here' })).toBeInTheDocument()
  })

  it('continues from the first incomplete lesson when nothing is in progress', async () => {
    const progress = [{ lesson_id: 'lesson-1', percent: 100, status: 'completed', completed_at: '2026-01-01', updated_at: '2026-01-01T10:00:00Z' }]
    vi.stubGlobal('fetch', vi.fn<typeof fetch>((input) => {
      const url = requestUrl(input)
      if (url.endsWith('/api/v1/learner/courses')) return response([courses[0]])
      if (url.includes('/progress')) return response(progress)
      return response(snapshot)
    }))
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /First course/i }))

    expect(await screen.findByRole('heading', { name: 'Older lesson' })).toBeInTheDocument()
  })

  it('opens a course from an access link and renders safe Markdown text nodes', async () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>((input) => {
      const url = requestUrl(input)
      if (url.includes('/access/')) return response({ email: 'learner@example.com', course_title: 'First course', ready: true })
      if (url.endsWith('/session')) return response({ ok: true, course_id: 'course-1' })
      if (url.includes('/progress')) return response([])
      return response(snapshot)
    }))
    renderPage('/app/access/access-token')
    await waitFor(() => { expect(window.location.pathname).toBe('/app/') })
    fireEvent.click(await screen.findByRole('button', { name: /открыть курс/i }))
    fireEvent.click(await screen.findByRole('button', { name: 'Recent lesson' }))

    expect(await screen.findByRole('heading', { name: 'Continue here' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /отметить урок завершённым/i })).toBeInTheDocument()
  })

  it('creates an in-memory transfer code in an authenticated browser tab', async () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>((input) => {
      const url = requestUrl(input)
      if (url.endsWith('/api/v1/learner/courses')) return response([courses[0]])
      if (url.endsWith('/api/v1/learner/csrf')) return response({ csrfToken: 'learner-csrf' })
      if (url.endsWith('/api/v1/learner/pwa-transfer')) return response({ code: 'transfer-code-only-in-memory', expires_at: '2099-01-01T10:00:00Z' }, 201)
      if (url.includes('/progress')) return response([])
      return response(snapshot)
    }))
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: 'Перенести вход в установленное приложение' }))

    expect(await screen.findByText('transfer-code-only-in-memory')).toBeInTheDocument()
    expect(window.localStorage.length).toBe(0)
    expect(window.location.pathname).toBe('/app/')
  })

  it('consumes a transfer code in standalone mode and loads courses without restart', async () => {
    setStandalone(true)
    let authenticated = false
    const requests: Array<{ url: string; body?: BodyInit | null }> = []
    vi.stubGlobal('fetch', vi.fn<typeof fetch>((input, options) => {
      const url = requestUrl(input)
      requests.push({ url, body: options?.body })
      if (url.endsWith('/api/v1/learner/csrf')) return response({ csrfToken: 'learner-csrf' })
      if (url.endsWith('/api/v1/learner/pwa-transfer/consume')) {
        authenticated = true
        return response({ ok: true })
      }
      if (url.endsWith('/api/v1/learner/courses')) return authenticated ? response(courses) : response({ code: 'NOT_AUTHENTICATED' }, 401)
      if (url.includes('/progress')) return response([])
      return response(snapshot)
    }))
    renderPage()

    expect(await screen.findByRole('heading', { name: 'Перенос входа' })).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Код переноса'), { target: { value: 'one-time-transfer-code' } })
    fireEvent.click(screen.getByRole('button', { name: 'Перенести вход' }))

    expect(await screen.findByRole('heading', { name: 'Все курсы' })).toBeInTheDocument()
    expect(window.location.pathname).toBe('/app/')
    expect(requests.some((item) => item.url.includes('one-time-transfer-code'))).toBe(false)
    expect(requests.find((item) => item.url.endsWith('/consume'))?.body).toBe(JSON.stringify({ code: 'one-time-transfer-code' }))
    expect(window.localStorage.length).toBe(0)
  })

  it('does not create a transfer when standalone PWA already has a session cookie', async () => {
    setStandalone(true)
    const fetchMock = vi.fn<typeof fetch>((input) => {
      const url = requestUrl(input)
      if (url.endsWith('/api/v1/learner/courses')) return response(courses)
      if (url.includes('/progress')) return response([])
      return response(snapshot)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderPage()

    expect(await screen.findByRole('heading', { name: 'Все курсы' })).toBeInTheDocument()
    expect(screen.queryByLabelText('Код переноса')).not.toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([input]) => requestUrl(input).includes('/pwa-transfer'))).toBe(false)
  })

  it('accepts a pasted email link in standalone mode without navigating to it', async () => {
    setStandalone(true)
    let authenticated = false
    const requests: Array<{ url: string; body?: BodyInit | null }> = []
    vi.stubGlobal('fetch', vi.fn<typeof fetch>((input, options) => {
      const url = requestUrl(input)
      requests.push({ url, body: options?.body })
      if (url.endsWith('/api/v1/learner/csrf')) return response({ csrfToken: 'learner-csrf' })
      if (url.endsWith('/api/v1/learner/session')) {
        authenticated = true
        return response({ ok: true, course_id: 'course-1' })
      }
      if (url.endsWith('/api/v1/learner/courses')) return authenticated ? response(courses) : response({ code: 'NOT_AUTHENTICATED' }, 401)
      if (url.includes('/progress')) return response([])
      return response(snapshot)
    }))
    renderPage()

    await screen.findByRole('heading', { name: 'Перенос входа' })
    fireEvent.click(screen.getByText('Резервный вход по ссылке из письма'))
    fireEvent.change(screen.getByLabelText('Полная ссылка из письма'), { target: { value: 'https://learning.example/app/access/email-secret-token' } })
    fireEvent.click(screen.getByRole('button', { name: 'Войти по ссылке' }))

    expect(await screen.findByRole('heading', { name: 'Все курсы' })).toBeInTheDocument()
    expect(window.location.pathname).toBe('/app/')
    expect(requests.some((item) => item.url.includes('email-secret-token'))).toBe(false)
    expect(requests.find((item) => item.url.endsWith('/session'))?.body).toBe(JSON.stringify({ token: 'email-secret-token' }))
  })

  it('renders learner video without a direct storage URL and with browser UI restrictions', async () => {
    const videoSnapshot = {
      ...snapshot,
      modules: [{ id: 'module-1', title: 'Module', description: '', lessons: [{
        id: 'lesson-video',
        title: 'Video lesson',
        description: '',
        content_units: [
          { id: 'unit-video', type: 'video', title: 'Protected video', position: 1, text_markdown: null, media_asset_id: 'asset-1', is_downloadable: false },
          { id: 'unit-audio', type: 'audio', title: 'Protected audio', position: 2, text_markdown: null, media_asset_id: 'asset-2', is_downloadable: false },
        ],
      }] }],
    }
    const proxyUrl = '/api/v1/learner/courses/course-1/media/asset-1/content'
    vi.stubGlobal('fetch', vi.fn<typeof fetch>((input) => {
      const url = requestUrl(input)
      if (url.endsWith('/api/v1/learner/courses')) return response([courses[0]])
      if (url.endsWith('/stream-url')) return response({ url: proxyUrl })
      if (url.includes('/progress')) return response([])
      return response(videoSnapshot)
    }))
    const view = renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /First course/i }))

    await waitFor(() => { expect(view.container.querySelector('video')).not.toBeNull() })
    const video = view.container.querySelector('video')
    const audio = view.container.querySelector('audio')
    expect(video).toHaveAttribute('controlsList', 'nodownload noremoteplayback')
    expect(video).toHaveAttribute('disablePictureInPicture')
    expect(audio).toHaveAttribute('controlsList', 'nodownload noremoteplayback')
    expect(video?.getAttribute('src')).toBe(proxyUrl)
    expect(video?.outerHTML).not.toContain('private/')
    expect(video?.outerHTML).not.toContain('s3')
    expect(screen.getByText('learner@example.com · abcd1234')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Скачать курс' })).not.toBeInTheDocument()
  })

  it('shows course download only for media allowed for offline viewing', async () => {
    const allowedSnapshot = {
      ...snapshot,
      modules: [{ id: 'module-1', title: 'Module', description: '', lessons: [{
        id: 'lesson-video',
        title: 'Video lesson',
        description: '',
        content_units: [{ id: 'unit-video', type: 'video', title: 'Video', position: 1, text_markdown: null, media_asset_id: 'asset-1', is_downloadable: true }],
      }] }],
    }
    vi.stubGlobal('fetch', vi.fn<typeof fetch>((input) => {
      const url = requestUrl(input)
      if (url.endsWith('/api/v1/learner/courses')) return response([courses[0]])
      if (url.includes('/progress')) return response([])
      if (url.endsWith('/stream-url')) return response({ url: '/api/v1/learner/media' })
      return response(allowedSnapshot)
    }))
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /First course/i }))

    expect(await screen.findByRole('button', { name: 'Скачать курс' })).toBeInTheDocument()
  })

  it('falls back to offline media when the stream API fails while navigator.onLine is true', async () => {
    const offlinePackage: OfflinePackage = {
      courseId: 'course-1', packageId: 'package-1', revisionId: 'revision-1', revision: 1,
      title: 'First course', shortDescription: '', licenseToken: 'fixture',
      licenseClaims: { license_id: 'license', learner_id: 'learner-1', course_id: 'course-1', revision_id: 'revision-1', revision: 1, device_id: 'device', session_id: 'session', issued_at: 1, expires_at: 4102444800, iat: 1, exp: 4102444800 },
      learnerId: 'learner-1', sessionId: 'session', snapshotIv: new ArrayBuffer(12), snapshotCiphertext: new ArrayBuffer(1),
      assets: [{ id: 'asset-1', content_type: 'video/mp4', size_bytes: 6, sha256: '0'.repeat(64), chunk_size: 4, chunk_count: 2 }],
      totalSize: 6, storageKind: 'idb', status: 'ready', updateAvailable: false, createdAt: Date.now(),
    }
    Object.defineProperty(navigator, 'onLine', { configurable: true, value: true })
    vi.stubGlobal('fetch', vi.fn<typeof fetch>(() => response({ code: 'NETWORK_UNAVAILABLE' }, 503)))
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const view = render(<QueryClientProvider client={queryClient}><MediaUnit courseId="course-1" unit={{ id: 'unit-video', type: 'video', title: 'Video', position: 1, text_markdown: null, media_asset_id: 'asset-1', is_downloadable: true }} watermark="learner@example.com" offlinePackage={offlinePackage} offlineAssetAvailable snapshotLoadedOffline={false} /></QueryClientProvider>)

    await waitFor(() => { expect(view.container.querySelector('video')).toHaveAttribute('src', '/offline-media/course-1/asset-1') })
  })
})
