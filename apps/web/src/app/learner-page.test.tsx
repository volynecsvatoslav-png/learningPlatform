import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { LearnerPage } from './learner-page'

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

const courses = [
  { id: 'course-1', title: 'First course', short_description: 'First route', description_markdown: '', cover_asset_id: null },
  { id: 'course-2', title: 'Second course', short_description: 'Second route', description_markdown: '', cover_asset_id: null },
]

const snapshot = {
  title: 'First course',
  description_markdown: '',
  modules: [{ id: 'module-1', title: 'Module', description: '', lessons: [
    { id: 'lesson-1', title: 'Completed lesson', description: '', content_units: [] },
    { id: 'lesson-2', title: 'Older lesson', description: '', content_units: [] },
    { id: 'lesson-3', title: 'Recent lesson', description: '', content_units: [{ id: 'unit-1', type: 'text', title: '', position: 1, text_markdown: '# Continue here', media_asset_id: null }] },
  ] }],
}

describe('LearnerPage', () => {
  afterEach(() => vi.unstubAllGlobals())

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
    fireEvent.click(await screen.findByRole('button', { name: /открыть курс/i }))
    fireEvent.click(await screen.findByRole('button', { name: 'Recent lesson' }))

    expect(await screen.findByRole('heading', { name: 'Continue here' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /отметить урок завершённым/i })).toBeInTheDocument()
  })
})
