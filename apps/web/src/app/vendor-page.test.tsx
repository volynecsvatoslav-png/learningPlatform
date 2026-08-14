import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { NewContent, VendorPage } from './vendor-page'

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}><VendorPage /></QueryClientProvider>)
}

function response(data: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(data), { status }))
}

function workspaceResponse(url: string) {
  if (url.includes('/api/v1/vendor/courses?')) return response([])
  if (url.includes('/api/v1/vendor/access?')) return response([])
  if (url.includes('/api/v1/vendor/media?')) return response([])
  if (url.includes('/api/v1/vendor/members?')) return response([])
  return response({})
}

describe('VendorPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('restores an existing vendor session before showing login', async () => {
    const fetchMock = vi.fn<typeof fetch>((input) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
      if (url.endsWith('/api/v1/vendor/me')) return response({ email: 'owner@example.com', vendors: [{ id: 'vendor-1', name: 'Alpha', role: 'owner' }] })
      return workspaceResponse(url)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderPage()

    expect(await screen.findByRole('heading', { name: 'Alpha' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Войти в кабинет' })).not.toBeInTheDocument()
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/v1/vendor/me')
  })

  it('shows login only after an auth error and loads the workspace after login', async () => {
    let authenticated = false
    const fetchMock = vi.fn<typeof fetch>((input) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
      if (url.endsWith('/api/v1/vendor/csrf')) return response({ csrfToken: 'csrf-token' })
      if (url.endsWith('/api/v1/vendor/auth/login')) { authenticated = true; return response({ ok: true }) }
      if (url.endsWith('/api/v1/vendor/me')) return authenticated
        ? response({ email: 'owner@example.com', vendors: [{ id: 'vendor-1', name: 'Alpha', role: 'owner' }] })
        : response({ code: 'NOT_AUTHENTICATED' }, 401)
      return workspaceResponse(url)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderPage()

    expect(await screen.findByRole('heading', { name: 'Войти в кабинет' })).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'owner@example.com' } })
    fireEvent.change(screen.getByLabelText('Пароль'), { target: { value: 'correct horse battery staple' } })
    fireEvent.click(screen.getByRole('button', { name: /войти/i }))

    expect(await screen.findByRole('heading', { name: 'Alpha' })).toBeInTheDocument()
    expect(await screen.findByText('Курсов пока нет. Создайте первый маршрут обучения.')).toBeInTheDocument()
  })

  it('does not replace a non-authentication failure with the login form', async () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>(() => response({ code: 'SERVER_ERROR' }, 500)))
    renderPage()

    expect(await screen.findByRole('heading', { name: 'Кабинет недоступен' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Войти в кабинет' })).not.toBeInTheDocument()
  })

  it('creates a course from a restored session', async () => {
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
      if (url.endsWith('/api/v1/vendor/me')) return response({ email: 'owner@example.com', vendors: [{ id: 'vendor-1', name: 'Alpha', role: 'owner' }] })
      if (url.endsWith('/api/v1/vendor/csrf')) return response({ csrfToken: 'csrf-token' })
      if (url.includes('/api/v1/vendor/courses?') && init?.method === 'POST') return response({ id: 'course-1' }, 201)
      return workspaceResponse(url)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderPage()
    await screen.findByRole('heading', { name: 'Alpha' })

    fireEvent.click(screen.getByRole('button', { name: /новый курс/i }))
    fireEvent.change(screen.getByLabelText('Название'), { target: { value: 'New course' } })
    fireEvent.change(screen.getByLabelText('Slug'), { target: { value: 'new-course' } })
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить курс' }))

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Alpha' })).toBeInTheDocument())
    const request = fetchMock.mock.calls.find(([input, init]) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
      return url.includes('/courses?') && init?.method === 'POST'
    })
    expect(request).toBeDefined()
  })

  it('uploads a video in the editor, shows validation, and selects it when ready', async () => {
    class FakeXHR {
      upload = { onprogress: () => {} }
      onerror: (() => void) | null = null
      onload: (() => void) | null = null
      status = 201
      responseText = JSON.stringify({ id: 'video-1', status: 'uploaded', kind: 'video', original_name: 'lesson.mp4' })
      open() { /* test transport */ }
      setRequestHeader() { /* test transport */ }
      send() {
        this.onload?.()
      }
    }
    vi.stubGlobal('XMLHttpRequest', FakeXHR)
    vi.stubGlobal('fetch', vi.fn<typeof fetch>((input) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
      if (url.endsWith('/api/v1/vendor/csrf')) return response({ csrfToken: 'csrf-token' })
      if (url.endsWith('/api/v1/vendor/media/video-1')) return response({ id: 'video-1', status: 'ready', kind: 'video', original_name: 'lesson.mp4' })
      return response({})
    }))
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><NewContent lessonId="lesson-1" readyMedia={[]} act={vi.fn()} vendorId="vendor-1" transferMode="proxy" /></QueryClientProvider>)
    fireEvent.change(screen.getByLabelText('Тип'), { target: { value: 'video' } })
    fireEvent.change(screen.getByLabelText('Новый файл'), { target: { files: [new File(['video'], 'lesson.mp4', { type: 'video/mp4' })] } })
    fireEvent.click(screen.getByRole('button', { name: 'Загрузить новый файл' }))
    expect(await screen.findByText('Файл готов и выбран.')).toBeInTheDocument()
    expect(screen.getByLabelText('Готовое медиа')).toHaveValue('video-1')
  })

  it('shows the backend upload error instead of a generic message', async () => {
    class ErrorXHR {
      upload = { onprogress: () => undefined }
      onload: (() => void) | null = null
      status = 400
      responseText = JSON.stringify({ file: ['Unsupported file format.'] })
      open() { /* test transport */ }
      setRequestHeader() { /* test transport */ }
      send() { this.onload?.() }
    }
    vi.stubGlobal('XMLHttpRequest', ErrorXHR)
    vi.stubGlobal('fetch', vi.fn<typeof fetch>(() => response({ csrfToken: 'csrf-token' })))
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><NewContent lessonId="lesson-1" readyMedia={[]} act={vi.fn()} vendorId="vendor-1" transferMode="proxy" /></QueryClientProvider>)
    fireEvent.change(screen.getByLabelText('Тип'), { target: { value: 'video' } })
    fireEvent.change(screen.getByLabelText('Новый файл'), { target: { files: [new File(['video'], 'lesson.txt', { type: 'text/plain' })] } })
    fireEvent.click(screen.getByRole('button', { name: 'Загрузить новый файл' }))
    expect(await screen.findByText('Unsupported file format.')).toBeInTheDocument()
  })
})
