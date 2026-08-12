import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, vendorApi, type Course, type MediaAsset, type Vendor } from '../lib/api'

function ErrorMessage({ error }: { error: Error | null }) {
  if (!error) return null
  return <p className="form-error">{error instanceof ApiError && error.code === 'AUTH_RATE_LIMITED' ? 'Слишком много попыток. Повторите позже.' : 'Не удалось выполнить запрос.'}</p>
}

function Login({ onLogin }: { onLogin: () => void }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [reset, setReset] = useState(false)
  const mutation = useMutation({ mutationFn: () => vendorApi.login(email, password), onSuccess: onLogin })
  const resetMutation = useMutation({ mutationFn: () => vendorApi.reset(email) })
  return (
    <main className="auth-layout">
      <section className="auth-card">
        <p className="eyebrow">Кабинет вендора</p>
        <h1>{reset ? 'Восстановить доступ' : 'Войти в кабинет'}</h1>
        <p className="muted">Управляйте курсами, медиа и доступами учеников.</p>
        <form onSubmit={(event) => { event.preventDefault(); if (reset) { resetMutation.mutate() } else { mutation.mutate() } }}>
          <label>Email<input type="email" value={email} onChange={(event) => { setEmail(event.target.value); }} required /></label>
          {!reset && <label>Пароль<input type="password" value={password} onChange={(event) => { setPassword(event.target.value); }} required /></label>}
          <button className="primary-action" type="submit">{reset ? 'Отправить письмо' : 'Войти'} <span aria-hidden="true">→</span></button>
        </form>
        <ErrorMessage error={mutation.error} />
        {resetMutation.isSuccess && <p className="form-success">Если аккаунт существует, письмо отправлено.</p>}
        <button className="text-button" onClick={() => { setReset(!reset); }}>{reset ? 'Вернуться ко входу' : 'Забыли пароль?'}</button>
      </section>
    </main>
  )
}

function CourseEditor({ vendor, course, onClose }: { vendor: Vendor; course: Course | null; onClose: () => void }) {
  const queryClient = useQueryClient()
  const [title, setTitle] = useState(course?.title ?? '')
  const [slug, setSlug] = useState(course?.slug ?? '')
  const [description, setDescription] = useState(course?.description_markdown ?? '')
  const [moduleTitle, setModuleTitle] = useState('')
  const [lessonTitle, setLessonTitle] = useState('')
  const [text, setText] = useState('')
  const [moduleId, setModuleId] = useState('')
  const [lessonId, setLessonId] = useState('')
  const id = course?.id
  const structure = useQuery({ queryKey: ['structure', id], queryFn: () => vendorApi.structure(id ?? ''), enabled: Boolean(id) })
  const save = useMutation({ mutationFn: () => course ? vendorApi.updateCourse(course.id, { title, slug, description_markdown: description }) : vendorApi.createCourse(vendor.id, { title, slug, short_description: '', description_markdown: description }), onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['courses', vendor.id] }); onClose() } })
  const action = useMutation({ mutationFn: (data: Record<string, unknown>) => vendorApi.structureAction(id ?? '', data), onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['structure', id] }) } })
  const publish = useMutation({ mutationFn: () => vendorApi.publish(id ?? ''), onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['courses', vendor.id] }) } })
  const archive = useMutation({ mutationFn: () => vendorApi.archiveCourse(id ?? ''), onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['courses', vendor.id] }); onClose() } })
  const preview = useMutation({ mutationFn: () => vendorApi.preview(id ?? '') })
  return <section className="panel editor-panel">
    <div className="panel-heading"><div><p className="eyebrow">Редактор</p><h2>{course ? 'Редактирование курса' : 'Новый курс'}</h2></div><button className="text-button" onClick={onClose}>Закрыть</button></div>
    <form className="course-form" onSubmit={(event) => { event.preventDefault(); save.mutate() }}><label>Название<input value={title} onChange={(event) => { setTitle(event.target.value); }} required /></label><label>Slug<input value={slug} onChange={(event) => { setSlug(event.target.value); }} required /></label><label>Описание Markdown<textarea value={description} onChange={(event) => { setDescription(event.target.value); }} /></label><button className="primary-action" type="submit">Сохранить</button></form>
    {id && <><div className="subsection"><h3>Структура курса</h3><div className="inline-form"><input placeholder="Новый модуль" value={moduleTitle} onChange={(event) => { setModuleTitle(event.target.value); }} /><button onClick={() => { action.mutate({ entity: 'module', action: 'create', title: moduleTitle, position: 1 }); setModuleTitle('') }}>Добавить модуль</button></div>{structure.isLoading && <p className="muted">Загрузка структуры...</p>}{structure.data?.modules.map((module) => <div className="tree-item" key={module.id}><strong>{module.title}</strong><button onClick={() => { setModuleId(module.id); setLessonId('') }}>Выбрать</button>{module.id === moduleId && <div className="inline-form"><input placeholder="Новый урок" value={lessonTitle} onChange={(event) => { setLessonTitle(event.target.value); }} /><button onClick={() => { action.mutate({ entity: 'lesson', action: 'create', parent_id: module.id, title: lessonTitle, position: 1 }); setLessonTitle('') }}>Добавить урок</button></div>}{module.lessons.map((lesson) => <div className="tree-child" key={lesson.id}><span>{lesson.title}</span><button onClick={() => { setLessonId(lesson.id); }}>Контент</button>{lesson.id === lessonId && <div className="inline-form"><input placeholder="Markdown-текст" value={text} onChange={(event) => { setText(event.target.value); }} /><button onClick={() => { action.mutate({ entity: 'content', action: 'create', parent_id: lesson.id, type: 'text', text_markdown: text, position: 1 }); setText('') }}>Добавить текст</button></div>}</div>)}</div>)}</div><div className="inline-form"><button className="primary-action" onClick={() => { publish.mutate(); }}>Опубликовать ревизию →</button><button onClick={() => { preview.mutate(); }}>Предпросмотр</button><button onClick={() => { archive.mutate(); }}>Архивировать</button></div>{preview.data && <pre className="preview-json">{JSON.stringify(preview.data, null, 2)}</pre>}<ErrorMessage error={save.error ?? action.error ?? publish.error ?? archive.error} /></>}
  </section>
}

export function VendorPage() {
  const [authenticated, setAuthenticated] = useState(false)
  const [selected, setSelected] = useState<Course | null | undefined>(undefined)
  const [vendor, setVendor] = useState<Vendor | null>(null)
  const me = useQuery({ queryKey: ['vendor-me'], queryFn: vendorApi.me, enabled: authenticated })
  const activeVendor = vendor ?? me.data?.vendors[0] ?? null
  const courses = useQuery({ queryKey: ['courses', activeVendor?.id], queryFn: () => vendorApi.courses(activeVendor?.id ?? ''), enabled: Boolean(activeVendor) })
  const accesses = useQuery({ queryKey: ['access', activeVendor?.id], queryFn: () => vendorApi.accesses(activeVendor?.id ?? ''), enabled: Boolean(activeVendor && activeVendor.role === 'owner') })
  const queryClient = useQueryClient()
  const logout = useMutation({ mutationFn: vendorApi.logout, onSuccess: () => { setAuthenticated(false); setVendor(null); queryClient.clear() } })
  if (!authenticated) return <Login onLogin={() => { setAuthenticated(true); }} />
  if (me.isLoading || !activeVendor) return <main className="loading-screen">Загрузка кабинета...</main>
  if (selected !== undefined) return <CourseEditor vendor={activeVendor} course={selected} onClose={() => { setSelected(undefined); }} />
  return <main className="workspace"><header className="workspace-header"><div><p className="eyebrow">Кабинет вендора</p><h1>{activeVendor.name}</h1></div><button className="text-button" onClick={() => { logout.mutate(); }}>Выйти</button></header><div className="workspace-grid"><section className="panel"><div className="panel-heading"><div><p className="eyebrow">Каталог</p><h2>Ваши курсы</h2></div><button className="primary-action" onClick={() => { setSelected(null); }}>Новый курс +</button></div>{courses.isLoading && <p className="muted">Загрузка курсов...</p>}{courses.isError && <p className="form-error">Курсы не загрузились.</p>}{courses.data?.length === 0 && <p className="empty-state">Курсов пока нет. Создайте первый маршрут обучения.</p>}<div className="course-list">{courses.data?.map((course) => <button className="course-row" key={course.id} onClick={() => { setSelected(course); }}><span><strong>{course.title}</strong><small>{course.short_description || 'Без описания'}</small></span><span className={`status status-${course.status}`}>{course.status} · rev {course.published_revision ?? '—'}</span></button>)}</div></section><MediaPanel vendor={activeVendor} />{activeVendor.role === 'owner' && <AccessPanel vendor={activeVendor} accesses={accesses.data ?? []} />}</div></main>
}

function AccessPanel({ vendor, accesses }: { vendor: Vendor; accesses: Array<{ id: string; learner_email: string; course_title: string; status: string }> }) {
  const [email, setEmail] = useState('')
  const [courseIds, setCourseIds] = useState<string[]>([])
  const courses = useQuery({ queryKey: ['courses', vendor.id], queryFn: () => vendorApi.courses(vendor.id) })
  const queryClient = useQueryClient()
  const grant = useMutation({ mutationFn: () => vendorApi.grant(vendor.id, email, courseIds), onSuccess: () => { setEmail(''); setCourseIds([]); void queryClient.invalidateQueries({ queryKey: ['access', vendor.id] }) } })
  const revoke = useMutation({ mutationFn: vendorApi.revoke, onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['access', vendor.id] }) } })
  const reissue = useMutation({ mutationFn: vendorApi.reissue, onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['access', vendor.id] }) } })
  return <section className="panel"><p className="eyebrow">Доступы</p><h2>Ученики</h2><form className="access-form" onSubmit={(event) => { event.preventDefault(); grant.mutate() }}><input type="email" placeholder="email ученика" value={email} onChange={(event) => { setEmail(event.target.value); }} required /><select multiple value={courseIds} onChange={(event) => { setCourseIds(Array.from(event.target.selectedOptions, (option) => option.value)); }} required>{courses.data?.filter((course) => course.status === 'published').map((course) => <option key={course.id} value={course.id}>{course.title}</option>)}</select><button className="primary-action" type="submit">Выдать доступ</button></form>{accesses.length === 0 && <p className="empty-state">Выданных доступов пока нет.</p>}{accesses.map((access) => <div className="access-row" key={access.id}><span><strong>{access.learner_email}</strong><small>{access.course_title} · {access.status}</small></span><button onClick={() => { reissue.mutate(access.id); }}>Переотправить</button><button onClick={() => { revoke.mutate(access.id); }}>Отозвать</button></div>)}</section>
}

function MediaPanel({ vendor }: { vendor: Vendor }) {
  const [kind, setKind] = useState<MediaAsset['kind']>('image')
  const [file, setFile] = useState<File | null>(null)
  const [assetId, setAssetId] = useState<string | null>(null)
  const upload = useMutation({
    mutationFn: () => vendorApi.uploadMedia(vendor.id, file as File, kind),
    onSuccess: (asset) => { setAssetId(asset.id) },
  })
  const status = useQuery({
    queryKey: ['vendor-media', assetId],
    queryFn: () => vendorApi.mediaStatus(assetId as string),
    enabled: Boolean(assetId),
    refetchInterval: (query) => query.state.data?.status === 'ready' || query.state.data?.status === 'rejected' ? false : 1500,
  })
  return <section className="panel"><p className="eyebrow">Медиа</p><h2>Приватная загрузка</h2><p className="muted">Файл отправляется напрямую в MinIO. Прикрепить можно только после проверки.</p><div className="access-form"><select value={kind} onChange={(event) => { setKind(event.target.value as MediaAsset['kind']) }}><option value="image">Изображение</option><option value="audio">Аудио</option><option value="video">Видео</option></select><input type="file" accept={`${kind}/*`} onChange={(event) => { setFile(event.target.files?.[0] ?? null) }} /><button className="primary-action" disabled={!file || upload.isPending} onClick={() => { upload.mutate() }}>Загрузить и проверить</button></div>{upload.isPending && <p className="muted">Отправка файла...</p>}{status.data && <p className={status.data.status === 'ready' ? 'form-success' : status.data.status === 'rejected' ? 'form-error' : 'muted'}>Статус проверки: {status.data.status}{status.data.rejection_reason ? ` · ${status.data.rejection_reason}` : ''}</p>}{upload.error && <p className="form-error">Не удалось загрузить медиа.</p>}</section>
}
