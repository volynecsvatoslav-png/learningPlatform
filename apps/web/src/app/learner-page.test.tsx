import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { LearnerPage } from './learner-page'

function renderPage(path = '/app/access/access-token') {
  window.history.pushState({}, '', path)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <LearnerPage />
    </QueryClientProvider>,
  )
}

describe('LearnerPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('opens a course from an access link and renders Markdown content', async () => {
    const fetchMock = vi.fn<typeof fetch>((input) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
      if (url.includes('/access/')) return Promise.resolve(new Response(JSON.stringify({ email: 'learner@example.com', course_title: 'Course', ready: true }), { status: 200 }))
      if (url.endsWith('/session')) return Promise.resolve(new Response(JSON.stringify({ ok: true, course_id: 'course-1' }), { status: 200 }))
      if (url.endsWith('/course-1')) return Promise.resolve(new Response(JSON.stringify({ title: 'Course', description_markdown: '', modules: [{ id: 'module-1', title: 'Module', description: '', lessons: [{ id: 'lesson-1', title: 'Lesson', description: '', content_units: [{ id: 'unit-1', type: 'text', title: '', position: 1, text_markdown: '# Welcome', media_asset_id: null }] }] }] }), { status: 200 }))
      if (url.includes('/progress')) return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }))
      return Promise.resolve(new Response(JSON.stringify({}), { status: 200 }))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderPage()
    expect(await screen.findByRole('heading', { name: 'Course' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /открыть курс/i }))
    expect(await screen.findByRole('heading', { name: 'Welcome' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /отметить урок завершённым/i })).toBeInTheDocument()
  })

  it('shows the revoked-session state', async () => {
    const fetchMock = vi.fn<typeof fetch>((input) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
      if (url.includes('/access/')) return Promise.resolve(new Response(JSON.stringify({ email: 'learner@example.com', course_title: 'Course', ready: true }), { status: 200 }))
      if (url.endsWith('/session')) return Promise.resolve(new Response(JSON.stringify({ ok: true, course_id: 'course-1' }), { status: 200 }))
      return Promise.resolve(new Response(JSON.stringify({ code: 'SESSION_REVOKED' }), { status: 403 }))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /открыть курс/i }))
    expect(await screen.findByRole('heading', { name: /сессия открыта на другом устройстве/i })).toBeInTheDocument()
  })
})
