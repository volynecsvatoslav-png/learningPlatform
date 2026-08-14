export type Vendor = { id: string; name: string; role: 'owner' | 'editor' }
export type Course = {
  id: string
  title: string
  slug: string
  short_description: string
  description_markdown: string
  cover_asset_id: string | null
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
  is_downloadable?: boolean
}
export type Enrollment = {
  id: string
  learner_email: string
  course_id: string
  course_title: string
  status: 'active' | 'revoked'
}
export type MediaAsset = {
  id: string
  kind: 'image' | 'audio' | 'video'
  status: 'pending' | 'uploaded' | 'validating' | 'ready' | 'rejected'
  original_name: string
  rejection_reason: string | null
  created_at?: string
}
export type VendorMember = {
  id: string
  vendor_id: string
  email: string
  role: 'owner' | 'editor'
  created_at: string
}
export type LearnerCourse = {
  id: string
  title: string
  short_description: string
  description_markdown: string
  cover_asset_id: string | null
}
export type LearnerSnapshot = {
  id?: string
  title: string
  description_markdown: string
  modules: Array<{ id: string; title: string; description: string; lessons: Array<{ id: string; title: string; description: string; content_units: ContentUnit[] }> }>
}
export type LearnerProgress = {
  lesson_id: string
  percent: number
  status: 'in_progress' | 'completed'
  completed_at: string | null
  updated_at: string
}
export type MediaTransferMode = 'proxy' | 'presigned'

let csrfToken = ''

export class ApiError extends Error {
  status: number
  code?: string
  body: Record<string, unknown>

  constructor(status: number, code?: string, body: Record<string, unknown> = {}, message?: string) {
    super(message ?? code ?? `HTTP ${String(status)}`)
    this.status = status
    this.code = code
    this.body = body
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  headers.set('Accept', 'application/json')
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  if (options.method && options.method !== 'GET') {
    if (!csrfToken) await csrf()
    headers.set('X-CSRFToken', csrfToken)
  }
  const response = await fetch(path, { ...options, credentials: 'include', headers })
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as Record<string, unknown> & { code?: string }
    throw new ApiError(response.status, body.code, body)
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
  mediaConfig: () => request<{ mode: MediaTransferMode }>('/api/v1/vendor/media/config'),
  login: async (email: string, password: string) => {
    const result = await request<{ ok: true }>('/api/v1/vendor/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) })
    csrfToken = ''
    return result
  },
  logout: () => request<{ ok: true }>('/api/v1/vendor/auth/logout', { method: 'POST' }),
  reset: (email: string) => request<{ ok: true }>('/api/v1/vendor/auth/password-reset', { method: 'POST', body: JSON.stringify({ email }) }),
  resetPassword: (uid: string, token: string, password: string) => request<{ ok: true }>(`/api/v1/vendor/auth/password-reset/${encodeURIComponent(uid)}/${encodeURIComponent(token)}`, { method: 'POST', body: JSON.stringify({ password }) }),
  me: () => request<{ email: string; vendors: Vendor[] }>('/api/v1/vendor/me'),
  courses: (vendorId: string) => request<Course[]>(`/api/v1/vendor/courses?vendor_id=${vendorId}`),
  createCourse: (vendorId: string, data: Pick<Course, 'title' | 'slug' | 'short_description' | 'description_markdown'>) => request<Course>(`/api/v1/vendor/courses?vendor_id=${vendorId}`, { method: 'POST', body: JSON.stringify(data) }),
  updateCourse: (id: string, data: Partial<Course>) => request<Course>(`/api/v1/vendor/courses/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  archiveCourse: (id: string) => request<Course>(`/api/v1/vendor/courses/${id}/archive`, { method: 'POST' }),
  preview: (id: string) => request<LearnerSnapshot>(`/api/v1/vendor/courses/${id}/preview`),
  structure: (id: string) => request<{ modules: Array<Module & { lessons: Array<Lesson & { content_units: ContentUnit[] }> }> }>(`/api/v1/vendor/courses/${id}/structure`),
  structureAction: (id: string, data: Record<string, unknown>) => request<Module | Lesson | ContentUnit>(`/api/v1/vendor/courses/${id}/structure`, { method: 'POST', body: JSON.stringify(data) }),
  publish: (id: string) => request<{ revision: number }>(`/api/v1/vendor/courses/${id}/publish`, { method: 'POST' }),
  accesses: (vendorId: string) => request<Enrollment[]>(`/api/v1/vendor/access?vendor_id=${vendorId}`),
  grant: (vendorId: string, learnerEmail: string, courseIds: string[]) => request<Enrollment[]>('/api/v1/vendor/access/grant', { method: 'POST', body: JSON.stringify({ vendor_id: vendorId, learner_email: learnerEmail, course_ids: courseIds }) }),
  revoke: (id: string) => request<Enrollment>(`/api/v1/vendor/access/${id}/revoke`, { method: 'POST' }),
  reissue: (id: string) => request<Enrollment>(`/api/v1/vendor/access/${id}/reissue`, { method: 'POST' }),
  media: (vendorId: string) => request<MediaAsset[]>(`/api/v1/vendor/media?vendor_id=${encodeURIComponent(vendorId)}`),
  members: (vendorId: string) => request<VendorMember[]>(`/api/v1/vendor/members?vendor_id=${encodeURIComponent(vendorId)}`),
  createEditor: (vendorId: string, email: string, password: string) => request<VendorMember>('/api/v1/vendor/members', { method: 'POST', body: JSON.stringify({ vendor_id: vendorId, email, password, role: 'editor' }) }),
  deleteMember: (id: string) => request<undefined>(`/api/v1/vendor/members/${id}`, { method: 'DELETE' }),
  uploadMedia: async (mode: MediaTransferMode, vendorId: string, file: File, kind: MediaAsset['kind'], onProgress?: (value: number) => void) => {
    if (mode === 'proxy') {
      if (!csrfToken) await csrf()
      return new Promise<MediaAsset>((resolve, reject) => {
        const form = new FormData()
        form.append('vendor_id', vendorId)
        form.append('kind', kind)
        form.append('file', file)
        const xhr = new XMLHttpRequest()
        xhr.open('POST', '/api/v1/vendor/media/upload-file')
        xhr.withCredentials = true
        xhr.setRequestHeader('X-CSRFToken', csrfToken)
        xhr.upload.onprogress = (event) => { if (event.lengthComputable) onProgress?.(Math.round(event.loaded / event.total * 100)) }
        xhr.timeout = 0
        const networkError = (code: string) => { reject(new ApiError(0, code, {}, 'Не удалось передать файл. Проверьте соединение и повторите попытку.')) }
        xhr.onerror = () => { networkError('NETWORK_ERROR') }
        xhr.ontimeout = () => { networkError('UPLOAD_TIMEOUT') }
        xhr.onabort = () => { networkError('UPLOAD_ABORTED') }
        xhr.onload = () => {
          let parsed: unknown
          try {
            parsed = JSON.parse(xhr.responseText) as unknown
          } catch {
            reject(new ApiError(xhr.status, undefined, {}, 'Сервер вернул некорректный ответ.'))
            return
          }
          if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
            reject(new ApiError(xhr.status, undefined, {}, 'Сервер вернул некорректный ответ.'))
            return
          }
          const body = parsed as Record<string, unknown> & { code?: string }
          if (xhr.status >= 200 && xhr.status < 300) resolve(body as unknown as MediaAsset)
          else reject(new ApiError(xhr.status, body.code, body))
        }
        xhr.send(form)
      })
    }
    const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer())
    const sha256 = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')
    const created = await request<{ asset: MediaAsset; upload: { url: string; fields: Record<string, string> } }>('/api/v1/vendor/media/uploads', {
      method: 'POST',
      body: JSON.stringify({ vendor_id: vendorId, kind, original_name: file.name, content_type: file.type, size_bytes: file.size, sha256 }),
    })
    const form = new FormData()
    Object.entries(created.upload.fields).forEach(([key, value]) => { form.append(key, value) })
    form.append('file', file)
    const uploadResponse = await fetch(created.upload.url, { method: 'POST', body: form })
    if (!uploadResponse.ok) throw new ApiError(uploadResponse.status, 'MEDIA_UPLOAD_FAILED')
    return request<MediaAsset>(`/api/v1/vendor/media/${created.asset.id}/complete`, { method: 'POST' })
  },
  mediaStatus: (assetId: string) => request<MediaAsset>(`/api/v1/vendor/media/${assetId}`),
  streamUrl: (assetId: string) => request<{ url: string }>(`/api/v1/media/${assetId}/stream-url`),
}

export const learnerApi = {
  access: (token: string) => request<{ email: string; course_title: string; ready: boolean }>(`/api/v1/learner/access/${encodeURIComponent(token)}`),
  login: async (token: string) => {
    const result = await request<{ ok: true; course_id: string }>('/api/v1/learner/session', { method: 'POST', body: JSON.stringify({ token }) })
    csrfToken = ''
    return result
  },
  logout: () => request<{ ok: true }>('/api/v1/learner/logout', { method: 'POST' }),
  courses: () => request<LearnerCourse[]>('/api/v1/learner/courses'),
  course: (id: string) => request<LearnerSnapshot>(`/api/v1/learner/courses/${id}`),
  progress: (courseId: string) => request<LearnerProgress[]>(`/api/v1/learner/courses/${courseId}/progress`),
  saveProgress: (courseId: string, lessonId: string, percent: number) => request(`/api/v1/learner/courses/${courseId}/progress/${lessonId}`, { method: 'POST', body: JSON.stringify({ percent, status: percent === 100 ? 'completed' : 'in_progress' }) }),
  streamUrl: (courseId: string, assetId: string) => request<{ url: string }>(`/api/v1/learner/courses/${courseId}/media/${assetId}/stream-url`),
}
