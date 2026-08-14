import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ApiError,
  vendorApi,
  type ContentUnit,
  type Course,
  type Lesson,
  type MediaAsset,
  type MediaTransferMode,
  type Module,
  type Vendor,
  type VendorMember,
} from '../lib/api'

type StructureAction = Record<string, unknown>
type CourseStructure = { modules: Array<Module & { lessons: Array<Lesson & { content_units: ContentUnit[] }> }> }

function ErrorMessage({ error }: { error: Error | null }) {
  if (!error) return null
  const body = error instanceof ApiError ? error.body : {}
  const messages = Object.values(body).reduce<string[]>((result, value) => {
    if (Array.isArray(value)) return result.concat(value.filter((item): item is string => typeof item === 'string'))
    return result
  }, [])
  const message = error instanceof ApiError && error.code === 'AUTH_RATE_LIMITED' ? 'Слишком много попыток. Повторите позже.' : messages[0] ?? (error instanceof ApiError ? error.message : 'Не удалось выполнить запрос.')
  return <p className="form-error">{message}</p>
}

function Markdown({ text }: { text: string }) {
  return <>{text.split('\n').map((line, index) => {
    if (line.startsWith('# ')) return <h2 key={index}>{line.slice(2)}</h2>
    if (line.startsWith('## ')) return <h3 key={index}>{line.slice(3)}</h3>
    return <p key={index}>{line || '\u00a0'}</p>
  })}</>
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
        <form onSubmit={(event) => { event.preventDefault(); if (reset) resetMutation.mutate(); else mutation.mutate() }}>
          <label>Email<input type="email" value={email} onChange={(event) => { setEmail(event.target.value) }} required /></label>
          {!reset && <label>Пароль<input type="password" value={password} onChange={(event) => { setPassword(event.target.value) }} required /></label>}
          <button className="primary-action" type="submit" disabled={mutation.isPending || resetMutation.isPending}>{reset ? 'Отправить письмо' : 'Войти'} <span aria-hidden="true">→</span></button>
        </form>
        <ErrorMessage error={reset ? resetMutation.error : mutation.error} />
        {resetMutation.isSuccess && <p className="form-success">Если аккаунт существует, письмо отправлено.</p>}
        <button className="text-button" onClick={() => { setReset(!reset) }}>{reset ? 'Вернуться ко входу' : 'Забыли пароль?'}</button>
      </section>
    </main>
  )
}

function ContentEditor({ unit, lessonId, position, total, readyMedia, act }: {
  unit: ContentUnit
  lessonId: string
  position: number
  total: number
  readyMedia: MediaAsset[]
  act: (data: StructureAction) => void
}) {
  const [title, setTitle] = useState(unit.title)
  const [text, setText] = useState(unit.text_markdown ?? '')
  const [assetId, setAssetId] = useState(unit.media_asset_id ?? '')
  const compatibleMedia = readyMedia.filter((asset) => asset.kind === unit.type)
  const payload = unit.type === 'text'
    ? { type: unit.type, title, text_markdown: text }
    : { type: unit.type, title, media_asset_id: assetId }
  return (
    <div className="content-editor">
      <div className="editor-fields">
        <label>Название<input value={title} onChange={(event) => { setTitle(event.target.value) }} /></label>
        {unit.type === 'text'
          ? <label>Markdown<textarea value={text} onChange={(event) => { setText(event.target.value) }} /></label>
          : <label>Готовое медиа<select value={assetId} onChange={(event) => { setAssetId(event.target.value) }} required><option value="">Выберите файл</option>{compatibleMedia.map((asset) => <option key={asset.id} value={asset.id}>{asset.original_name}</option>)}</select></label>}
      </div>
      <div className="item-actions">
        <span className="status">{unit.type} · {position}/{total}</span>
        <button disabled={position === 1} onClick={() => { act({ entity: 'content', action: 'move', id: unit.id, parent_id: lessonId, position: position - 1 }) }}>Выше</button>
        <button disabled={position === total} onClick={() => { act({ entity: 'content', action: 'move', id: unit.id, parent_id: lessonId, position: position + 1 }) }}>Ниже</button>
        <button disabled={unit.type !== 'text' && !assetId} onClick={() => { act({ entity: 'content', action: 'update', id: unit.id, parent_id: lessonId, ...payload }) }}>Сохранить блок</button>
        <button className="danger-button" onClick={() => { act({ entity: 'content', action: 'delete', id: unit.id, parent_id: lessonId }) }}>Удалить блок</button>
      </div>
    </div>
  )
}

export function NewContent({ lessonId, readyMedia, act, vendorId, transferMode }: { lessonId: string; readyMedia: MediaAsset[]; act: (data: StructureAction) => void; vendorId: string; transferMode?: MediaTransferMode }) {
  const [type, setType] = useState<ContentUnit['type']>('text')
  const [title, setTitle] = useState('')
  const [text, setText] = useState('')
  const [assetId, setAssetId] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [uploadedId, setUploadedId] = useState<string | null>(null)
  const upload = useMutation({ mutationFn: () => transferMode ? vendorApi.uploadMedia(transferMode, vendorId, file as File, type as MediaAsset['kind'], setUploadProgress) : Promise.reject(new ApiError(503, 'MEDIA_CONFIG_UNAVAILABLE', {}, 'Режим передачи медиа ещё не определён.')), onSuccess: (asset) => { setUploadedId(asset.id) } })
  const uploadStatus = useQuery({ queryKey: ['editor-media-status', uploadedId], queryFn: () => vendorApi.mediaStatus(uploadedId as string), enabled: Boolean(uploadedId), refetchInterval: (query) => query.state.data?.status === 'ready' || query.state.data?.status === 'rejected' ? false : 1000 })
  useEffect(() => { if (uploadStatus.data?.status === 'ready') setAssetId(uploadStatus.data.id) }, [uploadStatus.data])
  const media = readyMedia.filter((asset) => asset.kind === type)
  const uploadedReady = uploadStatus.data?.status === 'ready' ? uploadStatus.data : null
  const mediaOptions = uploadedReady?.kind === type && !media.some((asset) => asset.id === uploadedReady.id) ? [...media, uploadedReady] : media
  const canCreate = type === 'text' ? Boolean(text.trim()) : Boolean(assetId)
  return (
    <div className="new-content-form">
      <h5>Новый контент-блок</h5>
      <div className="editor-fields compact-fields">
        <label>Тип<select value={type} onChange={(event) => { setType(event.target.value as ContentUnit['type']); setAssetId('') }}><option value="text">Текст</option><option value="image">Изображение</option><option value="audio">Аудио</option><option value="video">Видео</option></select></label>
        <label>Название<input value={title} onChange={(event) => { setTitle(event.target.value) }} /></label>
        {type === 'text'
          ? <label>Markdown<textarea value={text} onChange={(event) => { setText(event.target.value) }} /></label>
          : <><label>Готовое медиа<select value={assetId} onChange={(event) => { setAssetId(event.target.value) }}><option value="">Выберите файл</option>{mediaOptions.map((asset) => <option key={asset.id} value={asset.id}>{asset.original_name}</option>)}</select></label><label>Новый файл<input type="file" accept={`${type}/*`} onChange={(event) => { setFile(event.target.files?.[0] ?? null) }} /></label><button type="button" disabled={!file || !transferMode || upload.isPending} onClick={() => { upload.mutate() }}>Загрузить новый файл</button>{upload.isPending && <progress max="100" value={uploadProgress}>{uploadProgress}%</progress>}{uploadStatus.data && <small>{uploadStatus.data.status === 'ready' ? 'Файл готов и выбран.' : `Проверка: ${uploadStatus.data.status}`}</small>}{upload.error && <><ErrorMessage error={upload.error} /><button type="button" onClick={() => { upload.reset(); upload.mutate() }}>Повторить загрузку</button></>}</>}
      </div>
      <button disabled={!canCreate} onClick={() => {
        const content = type === 'text' ? { type, text_markdown: text } : { type, media_asset_id: assetId }
        act({ entity: 'content', action: 'create', parent_id: lessonId, title, ...content })
        setTitle(''); setText(''); setAssetId('')
      }}>Добавить блок</button>
    </div>
  )
}

function LessonEditor({ lesson, moduleId, position, total, readyMedia, act, vendorId, transferMode }: {
  lesson: Lesson & { content_units: ContentUnit[] }
  moduleId: string
  position: number
  total: number
  readyMedia: MediaAsset[]
  act: (data: StructureAction) => void
  vendorId: string
  transferMode?: MediaTransferMode
}) {
  const [open, setOpen] = useState(false)
  const [title, setTitle] = useState(lesson.title)
  const [description, setDescription] = useState(lesson.description)
  return (
    <div className="tree-child">
      <div className="tree-summary">
        <div><strong>{lesson.title}</strong><small>{lesson.is_published ? 'Опубликован в следующей ревизии' : 'Скрыт из публикации'}</small></div>
        <div className="item-actions">
          <button onClick={() => { setOpen(!open) }}>{open ? 'Свернуть' : 'Редактировать'}</button>
          <button disabled={position === 1} onClick={() => { act({ entity: 'lesson', action: 'move', id: lesson.id, parent_id: moduleId, position: position - 1 }) }}>Выше</button>
          <button disabled={position === total} onClick={() => { act({ entity: 'lesson', action: 'move', id: lesson.id, parent_id: moduleId, position: position + 1 }) }}>Ниже</button>
          <button onClick={() => { act({ entity: 'lesson', action: 'update', id: lesson.id, parent_id: moduleId, is_published: !lesson.is_published }) }}>{lesson.is_published ? 'Снять с публикации' : 'Опубликовать урок'}</button>
          <button className="danger-button" onClick={() => { act({ entity: 'lesson', action: 'delete', id: lesson.id, parent_id: moduleId }) }}>Удалить</button>
        </div>
      </div>
      {open && <div className="lesson-editor-body">
        <div className="editor-fields">
          <label>Название урока<input value={title} onChange={(event) => { setTitle(event.target.value) }} /></label>
          <label>Описание<textarea value={description} onChange={(event) => { setDescription(event.target.value) }} /></label>
        </div>
        <button onClick={() => { act({ entity: 'lesson', action: 'update', id: lesson.id, parent_id: moduleId, title, description }) }}>Сохранить урок</button>
        <h4>Контент урока</h4>
        {lesson.content_units.length === 0 && <p className="empty-state">Добавьте первый контент-блок.</p>}
        {lesson.content_units.map((unit, index) => <ContentEditor key={unit.id} unit={unit} lessonId={lesson.id} position={index + 1} total={lesson.content_units.length} readyMedia={readyMedia} act={act} />)}
         <NewContent lessonId={lesson.id} readyMedia={readyMedia} act={act} vendorId={vendorId} transferMode={transferMode} />
      </div>}
    </div>
  )
}

function ModuleEditor({ module, position, total, readyMedia, act, vendorId, transferMode }: {
  module: CourseStructure['modules'][number]
  position: number
  total: number
  readyMedia: MediaAsset[]
  act: (data: StructureAction) => void
  vendorId: string
  transferMode?: MediaTransferMode
}) {
  const [title, setTitle] = useState(module.title)
  const [description, setDescription] = useState(module.description)
  const [lessonTitle, setLessonTitle] = useState('')
  return (
    <div className="tree-item">
      <div className="editor-fields">
        <label>Название модуля<input value={title} onChange={(event) => { setTitle(event.target.value) }} /></label>
        <label>Описание<textarea value={description} onChange={(event) => { setDescription(event.target.value) }} /></label>
      </div>
      <div className="item-actions">
        <span className="status">Модуль {position}/{total}</span>
        <button onClick={() => { act({ entity: 'module', action: 'update', id: module.id, title, description }) }}>Сохранить модуль</button>
        <button disabled={position === 1} onClick={() => { act({ entity: 'module', action: 'move', id: module.id, position: position - 1 }) }}>Выше</button>
        <button disabled={position === total} onClick={() => { act({ entity: 'module', action: 'move', id: module.id, position: position + 1 }) }}>Ниже</button>
        <button className="danger-button" onClick={() => { act({ entity: 'module', action: 'delete', id: module.id }) }}>Удалить модуль</button>
      </div>
      <div className="lesson-list">
         {module.lessons.map((lesson, index) => <LessonEditor key={lesson.id} lesson={lesson} moduleId={module.id} position={index + 1} total={module.lessons.length} readyMedia={readyMedia} act={act} vendorId={vendorId} transferMode={transferMode} />)}
      </div>
      <div className="inline-form"><input aria-label={`Новый урок в ${module.title}`} placeholder="Новый урок" value={lessonTitle} onChange={(event) => { setLessonTitle(event.target.value) }} /><button disabled={!lessonTitle.trim()} onClick={() => { act({ entity: 'lesson', action: 'create', parent_id: module.id, title: lessonTitle, is_published: false }); setLessonTitle('') }}>Добавить урок</button></div>
    </div>
  )
}

function PreviewMedia({ unit, media }: { unit: ContentUnit; media: MediaAsset[] }) {
  const asset = media.find((item) => item.id === unit.media_asset_id)
  const stream = useQuery({
    queryKey: ['vendor-preview-media', unit.media_asset_id],
    queryFn: () => vendorApi.streamUrl(unit.media_asset_id ?? ''),
    enabled: Boolean(unit.media_asset_id),
  })
  if (stream.isLoading) return <p className="muted">Готовим медиа...</p>
  if (!stream.data) return <p className="form-error">Медиа недоступно.</p>
  if (unit.type === 'image') return <img className="lesson-image" src={stream.data.url} alt={unit.title || asset?.original_name || ''} />
  if (unit.type === 'audio') return <audio controls src={stream.data.url} />
  return <video controls src={stream.data.url} />
}

function PublishedPreview({ snapshot, media }: { snapshot: Awaited<ReturnType<typeof vendorApi.preview>>; media: MediaAsset[] }) {
  return (
    <section className="published-preview">
      <p className="eyebrow">Опубликованная версия</p>
      <h2>{snapshot.title}</h2>
      <div className="markdown-content"><Markdown text={snapshot.description_markdown} /></div>
      {snapshot.modules.map((module) => <section key={module.id} className="preview-module"><h3>{module.title}</h3><p>{module.description}</p>{module.lessons.map((lesson) => <article key={lesson.id} className="preview-lesson"><h4>{lesson.title}</h4><p>{lesson.description}</p>{lesson.content_units.map((unit) => <div key={unit.id} className="preview-unit">{unit.title && <strong>{unit.title}</strong>}{unit.type === 'text' ? <div className="markdown-content"><Markdown text={unit.text_markdown ?? ''} /></div> : <PreviewMedia unit={unit} media={media} />}</div>)}</article>)}</section>)}
    </section>
  )
}

function CourseEditor({ vendor, course, onClose, transferMode }: { vendor: Vendor; course: Course | null; onClose: () => void; transferMode?: MediaTransferMode }) {
  const queryClient = useQueryClient()
  const [title, setTitle] = useState(course?.title ?? '')
  const [slug, setSlug] = useState(course?.slug ?? '')
  const [shortDescription, setShortDescription] = useState(course?.short_description ?? '')
  const [description, setDescription] = useState(course?.description_markdown ?? '')
  const [coverAssetId, setCoverAssetId] = useState(course?.cover_asset_id ?? '')
  const [moduleTitle, setModuleTitle] = useState('')
  const id = course?.id
  const structure = useQuery({ queryKey: ['structure', id], queryFn: () => vendorApi.structure(id ?? ''), enabled: Boolean(id) })
  const media = useQuery({ queryKey: ['vendor-media', vendor.id], queryFn: () => vendorApi.media(vendor.id) })
  const readyMedia = media.data?.filter((asset) => asset.status === 'ready') ?? []
  const save = useMutation({
    mutationFn: () => {
      const data = { title, slug, short_description: shortDescription, description_markdown: description, cover_asset_id: coverAssetId || null }
      return course ? vendorApi.updateCourse(course.id, data) : vendorApi.createCourse(vendor.id, data)
    },
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['courses', vendor.id] }); onClose() },
  })
  const action = useMutation({ mutationFn: (data: StructureAction) => vendorApi.structureAction(id ?? '', data), onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['structure', id] }) } })
  const publish = useMutation({ mutationFn: () => vendorApi.publish(id ?? ''), onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['courses', vendor.id] }) } })
  const archive = useMutation({ mutationFn: () => vendorApi.archiveCourse(id ?? ''), onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['courses', vendor.id] }); onClose() } })
  const preview = useMutation({ mutationFn: () => vendorApi.preview(id ?? '') })
  return (
    <main className="workspace editor-workspace">
      <section className="panel editor-panel">
        <div className="panel-heading"><div><p className="eyebrow">Редактор</p><h2>{course ? 'Редактирование курса' : 'Новый курс'}</h2></div><button className="text-button" onClick={onClose}>Закрыть</button></div>
        <form className="course-form" onSubmit={(event) => { event.preventDefault(); save.mutate() }}>
          <div className="editor-fields"><label>Название<input value={title} onChange={(event) => { setTitle(event.target.value) }} required /></label><label>Slug<input value={slug} onChange={(event) => { setSlug(event.target.value) }} required /></label><label>Краткое описание<input value={shortDescription} onChange={(event) => { setShortDescription(event.target.value) }} /></label><label>Обложка<select value={coverAssetId} onChange={(event) => { setCoverAssetId(event.target.value) }}><option value="">Без обложки</option>{readyMedia.filter((asset) => asset.kind === 'image').map((asset) => <option key={asset.id} value={asset.id}>{asset.original_name}</option>)}</select></label></div>
          <label>Описание Markdown<textarea value={description} onChange={(event) => { setDescription(event.target.value) }} /></label>
          <button className="primary-action" type="submit" disabled={save.isPending}>Сохранить курс</button>
        </form>
         {id && <>
           <div className="subsection"><div className="panel-heading"><div><p className="eyebrow">Структура</p><h3>Модули и уроки</h3></div><span className="status">{structure.data?.modules.length ?? 0} модулей</span></div><div className="inline-form"><input aria-label="Название нового модуля" placeholder="Новый модуль" value={moduleTitle} onChange={(event) => { setModuleTitle(event.target.value) }} /><button disabled={!moduleTitle.trim()} onClick={() => { action.mutate({ entity: 'module', action: 'create', title: moduleTitle }); setModuleTitle('') }}>Добавить модуль</button></div>{structure.isLoading && <p className="muted">Загрузка структуры...</p>}{structure.data?.modules.map((module, index) => <ModuleEditor key={module.id} module={module} position={index + 1} total={structure.data.modules.length} readyMedia={readyMedia} act={(data) => { action.mutate(data) }} vendorId={vendor.id} transferMode={transferMode} />)}</div>
          <div className="item-actions course-actions"><button className="primary-action" onClick={() => { publish.mutate() }}>Опубликовать ревизию →</button><button onClick={() => { preview.mutate() }}>Показать опубликованную версию</button><button className="danger-button" onClick={() => { archive.mutate() }}>Архивировать</button></div>
          {preview.data && <PublishedPreview snapshot={preview.data} media={readyMedia} />}
        </>}
        <ErrorMessage error={save.error ?? action.error ?? publish.error ?? archive.error ?? preview.error} />
      </section>
    </main>
  )
}

export function VendorPage() {
  const [loggedOut, setLoggedOut] = useState(false)
  const [selected, setSelected] = useState<Course | null | undefined>(undefined)
  const [vendor, setVendor] = useState<Vendor | null>(null)
  const queryClient = useQueryClient()
  const me = useQuery({ queryKey: ['vendor-me'], queryFn: vendorApi.me, enabled: !loggedOut })
  const transfer = useQuery({ queryKey: ['media-transfer-config'], queryFn: vendorApi.mediaConfig, enabled: !loggedOut })
  const activeVendor = vendor ?? me.data?.vendors[0] ?? null
  const courses = useQuery({ queryKey: ['courses', activeVendor?.id], queryFn: () => vendorApi.courses(activeVendor?.id ?? ''), enabled: Boolean(activeVendor) })
  const accesses = useQuery({ queryKey: ['access', activeVendor?.id], queryFn: () => vendorApi.accesses(activeVendor?.id ?? ''), enabled: activeVendor?.role === 'owner' })
  const logout = useMutation({ mutationFn: vendorApi.logout, onSuccess: () => { setLoggedOut(true); setVendor(null); setSelected(undefined); queryClient.clear() } })
  const authError = me.error instanceof ApiError && (me.error.status === 401 || me.error.status === 403)
  if (loggedOut || authError) return <Login onLogin={() => { setLoggedOut(false); void queryClient.invalidateQueries({ queryKey: ['vendor-me'] }) }} />
  if (me.isLoading) return <main className="loading-screen">Загрузка кабинета...</main>
  if (me.isError || !activeVendor) return <main className="state-screen"><h1>Кабинет недоступен</h1><p>Не удалось восстановить сессию. Повторите попытку позже.</p></main>
  if (selected !== undefined) return <CourseEditor vendor={activeVendor} course={selected} transferMode={transfer.data?.mode} onClose={() => { setSelected(undefined) }} />
  const vendors = me.data?.vendors ?? []
  return (
    <main className="workspace">
      <header className="workspace-header"><div><p className="eyebrow">Кабинет вендора</p><h1>{activeVendor.name}</h1>{vendors.length > 1 && <select aria-label="Вендор" value={activeVendor.id} onChange={(event) => { setVendor(vendors.find((item) => item.id === event.target.value) ?? null) }}>{vendors.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select>}</div><button className="text-button" onClick={() => { logout.mutate() }}>Выйти</button></header>
      <div className="workspace-grid">
        <section className="panel"><div className="panel-heading"><div><p className="eyebrow">Каталог</p><h2>Ваши курсы</h2></div><button className="primary-action" onClick={() => { setSelected(null) }}>Новый курс +</button></div>{courses.isLoading && <p className="muted">Загрузка курсов...</p>}{courses.isError && <p className="form-error">Курсы не загрузились.</p>}{courses.data?.length === 0 && <p className="empty-state">Курсов пока нет. Создайте первый маршрут обучения.</p>}<div className="course-list">{courses.data?.map((course) => <button className="course-row" key={course.id} onClick={() => { setSelected(course) }}><span><strong>{course.title}</strong><small>{course.short_description || 'Без описания'}</small></span><span className={`status status-${course.status}`}>{course.status} · rev {course.published_revision ?? '—'}</span></button>)}</div></section>
         <MediaPanel vendor={activeVendor} transferMode={transfer.data?.mode} configError={transfer.error} />
        {activeVendor.role === 'owner' && <AccessPanel vendor={activeVendor} accesses={accesses.data ?? []} />}
        {activeVendor.role === 'owner' && <MembersPanel vendor={activeVendor} />}
      </div>
    </main>
  )
}

function AccessPanel({ vendor, accesses }: { vendor: Vendor; accesses: Array<{ id: string; learner_email: string; course_title: string; status: string }> }) {
  const [email, setEmail] = useState('')
  const [courseIds, setCourseIds] = useState<string[]>([])
  const courses = useQuery({ queryKey: ['courses', vendor.id], queryFn: () => vendorApi.courses(vendor.id) })
  const queryClient = useQueryClient()
  const grant = useMutation({ mutationFn: () => vendorApi.grant(vendor.id, email, courseIds), onSuccess: () => { setEmail(''); setCourseIds([]); void queryClient.invalidateQueries({ queryKey: ['access', vendor.id] }) } })
  const revoke = useMutation({ mutationFn: vendorApi.revoke, onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['access', vendor.id] }) } })
  const reissue = useMutation({ mutationFn: vendorApi.reissue, onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['access', vendor.id] }) } })
  return <section className="panel"><p className="eyebrow">Доступы</p><h2>Ученики</h2><form className="access-form" onSubmit={(event) => { event.preventDefault(); grant.mutate() }}><input aria-label="Email ученика" type="email" placeholder="email ученика" value={email} onChange={(event) => { setEmail(event.target.value) }} required /><select aria-label="Курсы ученика" multiple value={courseIds} onChange={(event) => { setCourseIds(Array.from(event.target.selectedOptions, (option) => option.value)) }} required>{courses.data?.filter((course) => course.status === 'published').map((course) => <option key={course.id} value={course.id}>{course.title}</option>)}</select><button className="primary-action" type="submit">Выдать доступ</button></form>{accesses.length === 0 && <p className="empty-state">Выданных доступов пока нет.</p>}{accesses.map((access) => <div className="access-row" key={access.id}><span><strong>{access.learner_email}</strong><small>{access.course_title} · {access.status}</small></span><button onClick={() => { reissue.mutate(access.id) }}>Переотправить</button><button onClick={() => { revoke.mutate(access.id) }}>Отозвать</button></div>)}</section>
}

function MembersPanel({ vendor }: { vendor: Vendor }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const queryClient = useQueryClient()
  const members = useQuery({ queryKey: ['vendor-members', vendor.id], queryFn: () => vendorApi.members(vendor.id) })
  const create = useMutation({ mutationFn: () => vendorApi.createEditor(vendor.id, email, password), onSuccess: () => { setEmail(''); setPassword(''); void queryClient.invalidateQueries({ queryKey: ['vendor-members', vendor.id] }) } })
  const remove = useMutation({ mutationFn: vendorApi.deleteMember, onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['vendor-members', vendor.id] }) } })
  return <section className="panel"><p className="eyebrow">Команда</p><h2>Редакторы</h2><p className="muted">Владельцы могут создать только учетную запись редактора.</p><form className="access-form" onSubmit={(event) => { event.preventDefault(); create.mutate() }}><label>Email редактора<input type="email" value={email} onChange={(event) => { setEmail(event.target.value) }} required /></label><label>Временный пароль<input type="password" minLength={15} value={password} onChange={(event) => { setPassword(event.target.value) }} required /></label><button className="primary-action" type="submit">Создать редактора</button></form>{members.data?.map((member: VendorMember) => <div className="access-row" key={member.id}><span><strong>{member.email}</strong><small>{member.role}</small></span>{member.role === 'editor' && <button className="danger-button" onClick={() => { remove.mutate(member.id) }}>Удалить</button>}</div>)}<ErrorMessage error={create.error ?? remove.error} /></section>
}

function MediaPanel({ vendor, transferMode, configError }: { vendor: Vendor; transferMode?: MediaTransferMode; configError: Error | null }) {
  const [kind, setKind] = useState<MediaAsset['kind']>('image')
  const [file, setFile] = useState<File | null>(null)
  const [assetId, setAssetId] = useState<string | null>(null)
  const queryClient = useQueryClient()
  const media = useQuery({ queryKey: ['vendor-media', vendor.id], queryFn: () => vendorApi.media(vendor.id) })
  const upload = useMutation({ mutationFn: () => transferMode ? vendorApi.uploadMedia(transferMode, vendor.id, file as File, kind) : Promise.reject(new ApiError(503, 'MEDIA_CONFIG_UNAVAILABLE', {}, 'Режим передачи медиа ещё не определён.')), onSuccess: (asset) => { setAssetId(asset.id); setFile(null); void queryClient.invalidateQueries({ queryKey: ['vendor-media', vendor.id] }) } })
  const status = useQuery({ queryKey: ['vendor-media-status', assetId], queryFn: () => vendorApi.mediaStatus(assetId as string), enabled: Boolean(assetId), refetchInterval: (query) => query.state.data?.status === 'ready' || query.state.data?.status === 'rejected' ? false : 1500 })
  useEffect(() => {
    if (status.data?.status === 'ready' || status.data?.status === 'rejected') void queryClient.invalidateQueries({ queryKey: ['vendor-media', vendor.id] })
  }, [queryClient, status.data?.status, vendor.id])
  const transferCopy = transferMode === 'proxy' ? 'Файл загружается через защищённый сервер платформы.' : transferMode === 'presigned' ? 'Файл загружается напрямую в объектное хранилище.' : 'Определяем режим передачи файла…'
  return <section className="panel"><p className="eyebrow">Медиа</p><h2>Библиотека</h2><p className="muted">{transferCopy} В курс можно добавить только готовое медиа.</p><div className="access-form"><select aria-label="Тип медиа" value={kind} onChange={(event) => { setKind(event.target.value as MediaAsset['kind']) }}><option value="image">Изображение</option><option value="audio">Аудио</option><option value="video">Видео</option></select><input aria-label="Файл медиа" type="file" accept={`${kind}/*`} onChange={(event) => { setFile(event.target.files?.[0] ?? null) }} /><button className="primary-action" disabled={!file || !transferMode || upload.isPending} onClick={() => { upload.mutate() }}>Загрузить и проверить</button></div>{transferMode === undefined && <p className="muted">{configError ? 'Не удалось получить режим передачи медиа. Повторите попытку.' : 'Загрузка конфигурации сервера…'}</p>}{upload.isPending && <p className="muted">Отправка файла...</p>}{status.data && <p className={status.data.status === 'ready' ? 'form-success' : status.data.status === 'rejected' ? 'form-error' : 'muted'}>Статус проверки: {status.data.status}{status.data.rejection_reason ? ` · ${status.data.rejection_reason}` : ''}</p>}<div className="media-list">{media.data?.map((asset) => <div className="media-row" key={asset.id}><span><strong>{asset.original_name}</strong><small>{asset.kind}</small></span><span className={`status status-${asset.status}`}>{asset.status}</span></div>)}</div><ErrorMessage error={upload.error ?? media.error} /></section>
}
