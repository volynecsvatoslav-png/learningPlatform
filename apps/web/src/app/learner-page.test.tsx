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

function requestBody(request?: { body?: BodyInit | null }): Record<string, unknown> {
  return JSON.parse(request?.body as string | undefined ?? '{}') as Record<string, unknown>
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
    for (const name of ['learning-platform-offline', 'lms-device']) {
      await new Promise<void>((resolve) => {
        const request = indexedDB.deleteDatabase(name)
        request.onsuccess = () => { resolve() }
        request.onerror = () => { resolve() }
        request.onblocked = () => { resolve() }
      })
    }
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

  it('activates a device from an access fragment link and opens the catalog', async () => {
    let authenticated = false
    const requests: Array<{ url: string; body?: BodyInit | null }> = []
    vi.stubGlobal('fetch', vi.fn<typeof fetch>((input, options) => {
      const url = requestUrl(input)
      requests.push({ url, body: options?.body })
      if (url.endsWith('/api/v1/learner/csrf')) return response({ csrfToken: 'learner-csrf' })
      if (url.endsWith('/api/v1/auth/access/inspect')) return response({ challenge: 'challenge-1' })
      if (url.endsWith('/api/v1/auth/access/exchange')) {
        authenticated = true
        return response({ ok: true })
      }
      if (url.endsWith('/api/v1/learner/courses')) return authenticated ? response(courses) : response({ code: 'NOT_AUTHENTICATED' }, 401)
      if (url.includes('/progress')) return response([])
      return response(snapshot)
    }))
    renderPage('/app/#access=access-token')
    await waitFor(() => { expect(window.location.pathname).toBe('/app/') })

    expect(await screen.findByRole('heading', { name: 'Все курсы' })).toBeInTheDocument()
    const exchange = requests.find((item) => item.url.endsWith('/api/v1/auth/access/exchange'))
    const body = requestBody(exchange)
    expect(body.token).toBe('access-token')
    expect(body.challenge).toBe('challenge-1')
    expect(typeof body.signature).toBe('string')
    expect((body.signature as string | undefined)?.length).toBeGreaterThan(0)
    expect(body.installation_id).toBeTruthy()
    expect(body.confirm_transfer).toBe(false)
    expect(requests.some((item) => item.url.includes('access-token'))).toBe(false)
    fireEvent.click(await screen.findByRole('button', { name: /First course/i }))
    fireEvent.click(await screen.findByRole('button', { name: 'Recent lesson' }))
    expect(await screen.findByRole('heading', { name: 'Recent lesson' })).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: 'Continue here' })).toBeInTheDocument()
  })

  it('asks to confirm a device transfer and replaces the active session', async () => {
    let authenticated = false
    const requests: Array<{ url: string; body?: BodyInit | null }> = []
    vi.stubGlobal('fetch', vi.fn<typeof fetch>((input, options) => {
      const url = requestUrl(input)
      requests.push({ url, body: options?.body })
      if (url.endsWith('/api/v1/learner/csrf')) return response({ csrfToken: 'learner-csrf' })
      if (url.endsWith('/api/v1/auth/access/inspect')) return response({ challenge: 'challenge-1' })
      if (url.endsWith('/api/v1/auth/access/exchange')) {
        const body = requestBody(options)
        if (!body.confirm_transfer) return response({ code: 'DEVICE_TRANSFER_CONFIRMATION_REQUIRED' }, 409)
        authenticated = true
        return response({ ok: true })
      }
      if (url.endsWith('/api/v1/learner/courses')) return authenticated ? response(courses) : response({ code: 'NOT_AUTHENTICATED' }, 401)
      if (url.includes('/progress')) return response([])
      return response(snapshot)
    }))
    renderPage('/app/#access=access-token')

    expect(await screen.findByRole('heading', { name: 'Перенос входа' })).toBeInTheDocument()
    fireEvent.click(await screen.findByRole('button', { name: 'Перенести вход на это устройство' }))

    expect(await screen.findByRole('heading', { name: 'Все курсы' })).toBeInTheDocument()
    const confirmed = requests.filter((item) => item.url.endsWith('/api/v1/auth/access/exchange'))
    expect(confirmed).toHaveLength(2)
    expect(requestBody(confirmed[1])).toMatchObject({ confirm_transfer: true, token: 'access-token' })
  })

  it('shows a session-ended screen when the heartbeat detects a replaced session', async () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>((input) => {
      const url = requestUrl(input)
      if (url.endsWith('/api/v1/learner/courses')) return response(courses)
      if (url.endsWith('/api/v1/auth/heartbeat')) return response({ code: 'SESSION_REPLACED' }, 401)
      if (url.includes('/progress')) return response([])
      return response(snapshot)
    }))
    renderPage()

    expect(await screen.findByRole('heading', { name: 'Все курсы' })).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: 'Сессия завершена' })).toBeInTheDocument()
    expect(screen.getByText('Вход выполнен на другом устройстве. Доступ к этому устройству закрыт.')).toBeInTheDocument()
  })

  it('recovers access from a recovery fragment link and signs the request', async () => {
    let authenticated = false
    const requests: Array<{ url: string; body?: BodyInit | null }> = []
    vi.stubGlobal('fetch', vi.fn<typeof fetch>((input, options) => {
      const url = requestUrl(input)
      requests.push({ url, body: options?.body })
      if (url.endsWith('/api/v1/learner/csrf')) return response({ csrfToken: 'learner-csrf' })
      if (url.endsWith('/api/v1/auth/recovery/exchange')) return response({ ok: true, access_token: 'fresh-token', access_link: 'https://learning.example/app/#access=fresh-token' })
      if (url.endsWith('/api/v1/auth/access/inspect')) return response({ challenge: 'challenge-1' })
      if (url.endsWith('/api/v1/auth/access/exchange')) {
        authenticated = true
        return response({ ok: true })
      }
      if (url.endsWith('/api/v1/learner/courses')) return authenticated ? response(courses) : response({ code: 'NOT_AUTHENTICATED' }, 401)
      if (url.includes('/progress')) return response([])
      return response(snapshot)
    }))
    renderPage('/app/#recovery=recovery-token')

    expect(await screen.findByRole('heading', { name: 'Все курсы' })).toBeInTheDocument()
    const recovery = requests.find((item) => item.url.endsWith('/api/v1/auth/recovery/exchange'))
    const body = requestBody(recovery)
    expect(body.recovery_token).toBe('recovery-token')
    expect(body.installation_id).toBeTruthy()
    expect(body.public_key_jwk).toMatchObject({ kty: 'EC', crv: 'P-256' })
    expect(typeof body.signature).toBe('string')
    expect(requests.some((item) => item.url.includes('recovery-token'))).toBe(false)
  })

  it('accepts a pasted email link in standalone mode without navigating to it', async () => {
    setStandalone(true)
    let authenticated = false
    const requests: Array<{ url: string; body?: BodyInit | null }> = []
    vi.stubGlobal('fetch', vi.fn<typeof fetch>((input, options) => {
      const url = requestUrl(input)
      requests.push({ url, body: options?.body })
      if (url.endsWith('/api/v1/learner/csrf')) return response({ csrfToken: 'learner-csrf' })
      if (url.endsWith('/api/v1/auth/access/inspect')) return response({ challenge: 'challenge-1' })
      if (url.endsWith('/api/v1/auth/access/exchange')) {
        authenticated = true
        return response({ ok: true })
      }
      if (url.endsWith('/api/v1/learner/courses')) return authenticated ? response(courses) : response({ code: 'NOT_AUTHENTICATED' }, 401)
      if (url.includes('/progress')) return response([])
      return response(snapshot)
    }))
    renderPage()

    await screen.findByRole('heading', { name: 'Вход в кабинет ученика' })
    fireEvent.change(screen.getByLabelText('Полная ссылка из письма'), { target: { value: 'https://learning.example/app/#access=pasted-token' } })
    fireEvent.click(screen.getByRole('button', { name: 'Войти по ссылке' }))

    expect(await screen.findByRole('heading', { name: 'Все курсы' })).toBeInTheDocument()
    expect(window.location.pathname).toBe('/app/')
    expect(requests.some((item) => item.url.includes('pasted-token'))).toBe(false)
    expect(requests.find((item) => item.url.endsWith('/api/v1/auth/access/exchange'))?.body).toContain('pasted-token')
  })

  it('ignores a legacy /app/access/<token> path and shows the login screen', async () => {
    setStandalone(true)
    const requests: Array<{ url: string; body?: BodyInit | null }> = []
    vi.stubGlobal('fetch', vi.fn<typeof fetch>((input, options) => {
      const url = requestUrl(input)
      requests.push({ url, body: options?.body })
      if (url.endsWith('/api/v1/learner/courses')) return response({ code: 'NOT_AUTHENTICATED' }, 401)
      return response({ code: 'NOT_AUTHENTICATED' }, 401)
    }))
    renderPage('/app/access/legacy-token')

    expect(await screen.findByRole('heading', { name: 'Вход в кабинет ученика' })).toBeInTheDocument()
    expect(window.location.pathname).toBe('/app/')
    expect(requests.some((item) => item.url.endsWith('/api/v1/auth/access/inspect'))).toBe(false)
    expect(requests.some((item) => item.url.endsWith('/api/v1/auth/access/exchange'))).toBe(false)
    expect(requests.some((item) => item.url.includes('legacy-token'))).toBe(false)
  })

  it('rejects a pasted legacy /app/access/<token> link', async () => {
    setStandalone(true)
    vi.stubGlobal('fetch', vi.fn<typeof fetch>(() => response({ code: 'NOT_AUTHENTICATED' }, 401)))
    renderPage()

    await screen.findByRole('heading', { name: 'Вход в кабинет ученика' })
    fireEvent.change(screen.getByLabelText('Полная ссылка из письма'), { target: { value: 'https://learning.example/app/access/legacy-token' } })
    fireEvent.click(screen.getByRole('button', { name: 'Войти по ссылке' }))

    expect(await screen.findByText('Вставьте полную ссылку из письма.')).toBeInTheDocument()
  })

  it('sends a recovery request with the entered email', async () => {
    setStandalone(true)
    const requests: Array<{ url: string; body?: BodyInit | null }> = []
    vi.stubGlobal('fetch', vi.fn<typeof fetch>((input, options) => {
      const url = requestUrl(input)
      requests.push({ url, body: options?.body })
      if (url.endsWith('/api/v1/learner/csrf')) return response({ csrfToken: 'learner-csrf' })
      if (url.endsWith('/api/v1/auth/recovery/request')) return response({ ok: true })
      return response({ code: 'NOT_AUTHENTICATED' }, 401)
    }))
    renderPage()

    fireEvent.click(await screen.findByText('Восстановить доступ'))
    fireEvent.change(screen.getByLabelText('Email ученика'), { target: { value: 'learner@example.com' } })
    fireEvent.click(screen.getByRole('button', { name: 'Отправить ссылку восстановления' }))

    expect(await screen.findByText(/Письмо отправлено/)).toBeInTheDocument()
    const recoveryRequest = requests.find((item) => item.url.endsWith('/api/v1/auth/recovery/request'))
    expect(recoveryRequest?.body).toContain('learner@example.com')
  })

  it('does not show transfer UI when the session cookie is already present', async () => {
    const fetchMock = vi.fn<typeof fetch>((input) => {
      const url = requestUrl(input)
      if (url.endsWith('/api/v1/learner/courses')) return response(courses)
      if (url.includes('/progress')) return response([])
      return response(snapshot)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderPage()

    expect(await screen.findByRole('heading', { name: 'Все курсы' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Перенос входа' })).not.toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([input]) => requestUrl(input).includes('/pwa-transfer'))).toBe(false)
    expect(fetchMock.mock.calls.some(([input]) => requestUrl(input).includes('/api/v1/auth/heartbeat'))).toBe(true)
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
      licenseClaims: { license_id: 'license', learner_id: 'learner-1', course_id: 'course-1', revision_id: 'revision-1', revision: 1, access_pass_id: 'pass-1', pass_generation: 1, device_id: 'device', issued_at: 1, expires_at: 4102444800, iat: 1, exp: 4102444800 },
      learnerId: 'learner-1', deviceId: 'device', accessPassId: 'pass-1', passGeneration: 1, snapshotIv: new ArrayBuffer(12), snapshotCiphertext: new ArrayBuffer(1),
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
