export type Vendor = { id: string; name: string; role: 'owner' | 'editor' }
export type Course = {
  id: string
  title: string
  slug: string
  short_description: string
  description_markdown: string
  status: 'draft' | 'published' | 'archived'
  offline_revision: number
  published_revision: number | null
}
export type Module = { id: string; title: string; description: string; position: number }
export type Lesson = {
  id: string
  title: string
  description: string
  position: number
  is_published: boolean
}
export type ContentUnit = {
  id: string
  type: 'text' | 'image' | 'audio' | 'video'
  title: string
  position: number
  text_markdown: string | null
  media_asset_id: string | null
}
export type Enrollment = {
  id: string
  learner_email: string
  course_id: string
  course_title: string
  status: 'active' | 'revoked'
}

let csrfToken = ''

export class ApiError extends Error {
  status: number
  code?: string

  constructor(status: number, code?: string) {
    super(code ?? `HTTP ${String(status)}`)
    this.status = status
    this.code = code
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  headers.set('Accept', 'application/json')
  if (options.body) headers.set('Content-Type', 'application/json')
  if (options.method && options.method !== 'GET') {
    if (!csrfToken) await csrf()
    headers.set('X-CSRFToken', csrfToken)
  }
  const response = await fetch(path, { ...options, credentials: 'include', headers })
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { code?: string }
    throw new ApiError(response.status, body.code)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export async function csrf(): Promise<string> {
  const response = await fetch('/api/v1/vendor/csrf', { credentials: 'include' })
  const body = (await response.json()) as { csrfToken: string }
  csrfToken = body.csrfToken
  return csrfToken
}

export const vendorApi = {
  login: (email: string, password: string) => request<{ ok: true }>('/api/v1/vendor/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }),
  logout: () => request<{ ok: true }>('/api/v1/vendor/auth/logout', { method: 'POST' }),
  reset: (email: string) => request<{ ok: true }>('/api/v1/vendor/auth/password-reset', { method: 'POST', body: JSON.stringify({ email }) }),
  me: () => request<{ email: string; vendors: Vendor[] }>('/api/v1/vendor/me'),
  courses: (vendorId: string) => request<Course[]>(`/api/v1/vendor/courses?vendor_id=${vendorId}`),
  createCourse: (vendorId: string, data: Pick<Course, 'title' | 'slug' | 'short_description' | 'description_markdown'>) => request<Course>(`/api/v1/vendor/courses?vendor_id=${vendorId}`, { method: 'POST', body: JSON.stringify(data) }),
  updateCourse: (id: string, data: Partial<Course>) => request<Course>(`/api/v1/vendor/courses/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  structure: (id: string) => request<{ modules: Array<Module & { lessons: Array<Lesson & { content_units: ContentUnit[] }> }> }>(`/api/v1/vendor/courses/${id}/structure`),
  structureAction: (id: string, data: Record<string, unknown>) => request<Module | Lesson | ContentUnit>(`/api/v1/vendor/courses/${id}/structure`, { method: 'POST', body: JSON.stringify(data) }),
  publish: (id: string) => request<{ revision: number }>(`/api/v1/vendor/courses/${id}/publish`, { method: 'POST' }),
  accesses: (vendorId: string) => request<Enrollment[]>(`/api/v1/vendor/access?vendor_id=${vendorId}`),
  grant: (vendorId: string, learnerEmail: string, courseIds: string[]) => request<Enrollment[]>('/api/v1/vendor/access/grant', { method: 'POST', body: JSON.stringify({ vendor_id: vendorId, learner_email: learnerEmail, course_ids: courseIds }) }),
  revoke: (id: string) => request<Enrollment>(`/api/v1/vendor/access/${id}/revoke`, { method: 'POST' }),
  reissue: (id: string) => request<Enrollment>(`/api/v1/vendor/access/${id}/reissue`, { method: 'POST' }),
}
