import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { VendorPage } from './vendor-page'

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <VendorPage />
    </QueryClientProvider>,
  )
}

function mockFetch() {
  const fetchMock = vi.fn<typeof fetch>((input, init) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
    if (url.endsWith('/api/v1/vendor/csrf')) {
      return Promise.resolve(new Response(JSON.stringify({ csrfToken: 'csrf-token' }), { status: 200 }))
    }
    if (url.endsWith('/api/v1/vendor/auth/login')) {
      return Promise.resolve(new Response(JSON.stringify({ ok: true }), { status: 200 }))
    }
    if (url.endsWith('/api/v1/vendor/me')) {
      return Promise.resolve(new Response(JSON.stringify({ email: 'owner@example.com', vendors: [{ id: 'vendor-1', name: 'Alpha', role: 'owner' }] }), { status: 200 }))
    }
    if (url.includes('/api/v1/vendor/access?')) {
      return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }))
    }
    if (url.includes('/api/v1/vendor/courses?')) {
      if (init?.method === 'POST') {
        return Promise.resolve(new Response(JSON.stringify({ id: 'course-1', title: 'New course', slug: 'new-course', short_description: '', description_markdown: '', status: 'draft', offline_revision: 1, published_revision: null }), { status: 201 }))
      }
      return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }))
    }
    return Promise.resolve(new Response(JSON.stringify({ modules: [] }), { status: 200 }))
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('VendorPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('logs in and loads the vendor workspace', async () => {
    mockFetch()
    renderPage()

    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'owner@example.com' } })
    fireEvent.change(screen.getByLabelText('Пароль'), { target: { value: 'correct horse battery staple' } })
    fireEvent.click(screen.getByRole('button', { name: /войти/i }))

    expect(await screen.findByRole('heading', { name: 'Alpha' })).toBeInTheDocument()
    expect(
      await screen.findByText('Курсов пока нет. Создайте первый маршрут обучения.'),
    ).toBeInTheDocument()
  })

  it('creates a course from the empty workspace', async () => {
    mockFetch()
    renderPage()
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'owner@example.com' } })
    fireEvent.change(screen.getByLabelText('Пароль'), { target: { value: 'correct horse battery staple' } })
    fireEvent.click(screen.getByRole('button', { name: /войти/i }))
    await screen.findByRole('heading', { name: 'Alpha' })

    fireEvent.click(screen.getByRole('button', { name: /новый курс/i }))
    fireEvent.change(screen.getByLabelText('Название'), { target: { value: 'New course' } })
    fireEvent.change(screen.getByLabelText('Slug'), { target: { value: 'new-course' } })
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }))

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Alpha' })).toBeInTheDocument())
  })
})
