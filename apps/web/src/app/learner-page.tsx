import { useEffect, useRef, useState } from 'react'
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, learnerApi, type ContentUnit, type LearnerCourse, type LearnerProgress, type LearnerSnapshot } from '../lib/api'
import { deleteAllOfflineCourses, deleteOfflineCourse, downloadOfflineCourse, formatBytes, getOfflinePackage, listOfflineCourses, offlineMediaUrl, readOfflineSnapshot, syncOfflineCourse, syncOfflineCourses, type OfflinePackage } from '../offline/offline-course'

function Markdown({ text }: { text: string }) {
  return <>{text.split('\n').map((line, index) => {
    if (line.startsWith('# ')) return <h2 key={index}>{line.slice(2)}</h2>
    if (line.startsWith('## ')) return <h3 key={index}>{line.slice(3)}</h3>
    return <p key={index}>{line || '\u00a0'}</p>
  })}</>
}

function takeAccessTokenFromLocation(): string | null {
  const legacyMatch = /^\/app\/access\/([^/]+)\/?$/.exec(window.location.pathname)
  const fragmentToken = new URLSearchParams(window.location.hash.slice(1)).get('access')
  const encoded = legacyMatch?.[1] ?? fragmentToken
  if (!encoded) return null
  window.history.replaceState({}, '', '/app/')
  try {
    return decodeURIComponent(encoded)
  } catch {
    return null
  }
}

function accessTokenFromPastedLink(value: string): string | null {
  try {
    const url = new URL(value.trim())
    if (!['http:', 'https:'].includes(url.protocol)) return null
    const legacyMatch = /^\/app\/access\/([^/]+)\/?$/.exec(url.pathname)
    const encoded = legacyMatch?.[1] ?? new URLSearchParams(url.hash.slice(1)).get('access')
    if (!encoded) return null
    return decodeURIComponent(encoded)
  } catch {
    return null
  }
}

function AccessLogin({ token, onLogin }: { token: string; onLogin: (courseId: string) => Promise<void> }) {
  const [pending, setPending] = useState(false)
  const [error, setError] = useState(false)
  const openCourse = async () => {
    setPending(true); setError(false)
    try {
      const result = await learnerApi.login(token)
      await onLogin(result.course_id)
    } catch {
      setError(true)
    } finally {
      setPending(false)
    }
  }
  return <main className="auth-layout"><section className="auth-card"><p className="eyebrow">Вход ученика</p><h1>Персональный доступ</h1><p className="muted">Откройте курс по ссылке из письма. На новом устройстве предыдущая сессия будет закрыта.</p><button className="primary-action" disabled={pending} onClick={() => { void openCourse() }}>{pending ? 'Открываем…' : 'Открыть курс'} <span aria-hidden="true">→</span></button>{error && <p className="form-error">Ссылка больше недействительна.</p>}</section></main>
}

function VideoMedia({ src, watermark }: { src: string; watermark: string }) {
  const [position, setPosition] = useState(0)
  useEffect(() => {
    const interval = window.setInterval(() => { setPosition((value) => (value + 1) % 4) }, 8000)
    return () => { window.clearInterval(interval) }
  }, [])
  return <div className="video-frame"><video controls controlsList="nodownload noremoteplayback" disablePictureInPicture onContextMenu={(event) => { event.preventDefault() }} src={src} /><span className={`video-watermark watermark-position-${String(position)}`}>{watermark}</span></div>
}

function useOnlineStatus() {
  const [online, setOnline] = useState(navigator.onLine)
  useEffect(() => {
    const update = () => { setOnline(navigator.onLine) }
    window.addEventListener('online', update)
    window.addEventListener('offline', update)
    return () => { window.removeEventListener('online', update); window.removeEventListener('offline', update) }
  }, [])
  return online
}

function useServiceWorkerReady() {
  const enabled = import.meta.env.PROD || import.meta.env.VITE_ENABLE_SERVICE_WORKER === 'true'
  const [ready, setReady] = useState('serviceWorker' in navigator && Boolean(navigator.serviceWorker.controller))
  useEffect(() => {
    if (!enabled || !('serviceWorker' in navigator)) return
    const update = () => { setReady(Boolean(navigator.serviceWorker.controller)) }
    navigator.serviceWorker.addEventListener('controllerchange', update)
    void navigator.serviceWorker.ready.then(update)
    return () => { navigator.serviceWorker.removeEventListener('controllerchange', update) }
  }, [enabled])
  return enabled && ready
}

function standaloneMedia(): MediaQueryList | null {
  try {
    return window.matchMedia('(display-mode: standalone)')
  } catch {
    return null
  }
}

function standaloneDisplayMode(): boolean {
  const iosNavigator = navigator as Navigator & { standalone?: boolean }
  return Boolean(standaloneMedia()?.matches) || Boolean(iosNavigator.standalone)
}

function useStandaloneMode() {
  const [standalone, setStandalone] = useState(standaloneDisplayMode)
  useEffect(() => {
    const media = standaloneMedia()
    const update = () => { setStandalone(standaloneDisplayMode()) }
    media?.addEventListener('change', update)
    window.addEventListener('pageshow', update)
    return () => {
      media?.removeEventListener('change', update)
      window.removeEventListener('pageshow', update)
    }
  }, [])
  return standalone
}

function TransferPanel() {
  const [transfer, setTransfer] = useState<{ code: string; expiresAt: string }>()
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)
  useEffect(() => {
    if (!transfer) return
    const delay = Math.min(2_147_483_647, Math.max(0, Date.parse(transfer.expiresAt) - Date.now()))
    const timeout = window.setTimeout(() => { setTransfer(undefined); setCopied(false) }, delay)
    return () => { window.clearTimeout(timeout) }
  }, [transfer])
  const create = async () => {
    setPending(true); setError(''); setCopied(false)
    try {
      const result = await learnerApi.createPwaTransfer()
      setTransfer({ code: result.code, expiresAt: result.expires_at })
    } catch {
      setError('Не удалось создать код. Обновите страницу и повторите попытку.')
    } finally {
      setPending(false)
    }
  }
  const copy = async () => {
    if (!transfer) return
    try {
      await navigator.clipboard.writeText(transfer.code)
      setCopied(true)
    } catch {
      setError('Не удалось скопировать код. Выделите и скопируйте его вручную.')
    }
  }
  return <section className="panel pwa-transfer-panel"><p className="eyebrow">Установленное приложение</p><h2>Перенос входа</h2><p className="muted">Откройте установленное приложение и введите одноразовый код. После переноса эта вкладка завершит работу.</p>{transfer ? <div className="transfer-code"><output aria-label="Код переноса">{transfer.code}</output><p>Код действует до {new Date(transfer.expiresAt).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}.</p><button onClick={() => { void copy() }}>Скопировать код</button>{copied && <span className="form-success">Скопировано</span>}</div> : <button className="primary-action" disabled={pending} onClick={() => { void create() }}>{pending ? 'Создаём код…' : 'Перенести вход в установленное приложение'}</button>}{error && <p className="form-error">{error}</p>}</section>
}

function PwaTransferLogin({ onAuthenticated }: { onAuthenticated: () => Promise<void> }) {
  const [code, setCode] = useState('')
  const [magicLink, setMagicLink] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const transfer = async () => {
    if (!code.trim()) return
    setPending(true); setError('')
    try {
      await learnerApi.consumePwaTransfer(code.trim())
      setCode(''); setMagicLink('')
      await onAuthenticated()
    } catch (reason) {
      setError(reason instanceof ApiError && reason.code === 'PWA_TRANSFER_RATE_LIMITED' ? 'Слишком много попыток. Подождите несколько минут.' : 'Код недействителен или истёк. Создайте новый код в обычном браузере.')
    } finally {
      setPending(false)
    }
  }
  const loginWithMagicLink = async () => {
    const token = accessTokenFromPastedLink(magicLink)
    if (!token) {
      setError('Вставьте полную ссылку из письма.')
      return
    }
    setPending(true); setError(''); setMagicLink('')
    try {
      await learnerApi.login(token)
      setCode('')
      await onAuthenticated()
    } catch {
      setError('Ссылка недействительна. Попросите владельца курса переотправить доступ.')
    } finally {
      setPending(false)
    }
  }
  return <main className="auth-layout"><section className="auth-card transfer-login"><p className="eyebrow">Установленное приложение</p><h1>Перенос входа</h1><p className="muted">Откройте ссылку из письма в обычном браузере, войдите в кабинет и нажмите «Перенести вход в установленное приложение». Затем введите показанный код здесь.</p><form onSubmit={(event) => { event.preventDefault(); void transfer() }} autoComplete="off"><label>Код переноса<input value={code} onChange={(event) => { setCode(event.target.value) }} autoComplete="off" spellCheck={false} /></label><button className="primary-action" type="submit" disabled={pending || !code.trim()}>Перенести вход</button></form><details><summary>Резервный вход по ссылке из письма</summary><form onSubmit={(event) => { event.preventDefault(); void loginWithMagicLink() }} autoComplete="off"><label>Полная ссылка из письма<input type="url" value={magicLink} onChange={(event) => { setMagicLink(event.target.value) }} autoComplete="off" spellCheck={false} /></label><button type="submit" disabled={pending || !magicLink.trim()}>Войти по ссылке</button></form></details>{error && <p className="form-error">{error}</p>}</section></main>
}

export function MediaUnit({ courseId, unit, watermark, offlinePackage, offlineAssetAvailable, snapshotLoadedOffline }: { courseId: string; unit: ContentUnit; watermark: string; offlinePackage?: OfflinePackage; offlineAssetAvailable: boolean; snapshotLoadedOffline: boolean }) {
  const media = useQuery({ queryKey: ['learner-media', courseId, unit.media_asset_id], queryFn: () => learnerApi.streamUrl(courseId, unit.media_asset_id ?? ''), enabled: Boolean(unit.media_asset_id), networkMode: 'always', retry: false })
  const offlineSource = offlineAssetAvailable ? offlineMediaUrl(courseId, unit.media_asset_id ?? '') : undefined
  const source = media.data?.url ?? offlineSource
  if (!media.data && offlineSource && offlinePackage && offlinePackage.licenseClaims.expires_at * 1000 <= Date.now()) return <p className="form-error">Подключитесь к интернету для продления офлайн-доступа.</p>
  if (media.isLoading && !source) return <p className="muted">Готовим воспроизведение...</p>
  if (!source && snapshotLoadedOffline && !offlineAssetAvailable) return <p className="form-error">Этот материал доступен только при подключении к интернету</p>
  if (!source) return <p className="form-error">Медиа недоступно.</p>
  if (unit.type === 'image') return <img className="lesson-image" src={source} alt={unit.title} />
  if (unit.type === 'audio') return <audio controls controlsList="nodownload noremoteplayback" onContextMenu={(event) => { event.preventDefault() }} src={source} />
  return <VideoMedia src={source} watermark={watermark} />
}

function continuationLesson(snapshot: LearnerSnapshot, progress: LearnerProgress[]): string | null {
  const lessons = snapshot.modules.flatMap((module) => module.lessons)
  const lessonIds = new Set(lessons.map((lesson) => lesson.id))
  const latestInProgress = progress
    .filter((row) => row.status === 'in_progress' && lessonIds.has(row.lesson_id))
    .sort((left, right) => Date.parse(right.updated_at) - Date.parse(left.updated_at))[0]
  if (latestInProgress) return latestInProgress.lesson_id
  const completed = new Set(progress.filter((row) => row.status === 'completed').map((row) => row.lesson_id))
  return lessons.find((lesson) => !completed.has(lesson.id))?.id ?? lessons[0]?.id ?? null
}

function CourseView({ courseId, onBack }: { courseId: string; onBack: () => void }) {
  const [lessonId, setLessonId] = useState<string | null>(null)
  const [recordedLessonId, setRecordedLessonId] = useState<string | null>(null)
  const [offlinePackage, setOfflinePackage] = useState<OfflinePackage>()
  const [offlinePackageLoaded, setOfflinePackageLoaded] = useState(false)
  const [downloadProgress, setDownloadProgress] = useState(0)
  const [downloadSize, setDownloadSize] = useState(0)
  const [downloadError, setDownloadError] = useState('')
  const [isDownloading, setIsDownloading] = useState(false)
  const downloadController = useRef<AbortController | null>(null)
  const online = useOnlineStatus()
  const queryClient = useQueryClient()
  const course = useQuery({ queryKey: ['learner-course', courseId], networkMode: 'always', queryFn: async () => {
    try { return { snapshot: await learnerApi.course(courseId), loadedFromOffline: false } } catch (error) { if (error instanceof ApiError && [401, 403].includes(error.status)) throw error; const local = await readOfflineSnapshot(courseId); if (local) return { snapshot: local, loadedFromOffline: true }; throw error instanceof Error ? error : new Error('Не удалось открыть курс.') }
  } })
  const progress = useQuery({ queryKey: ['learner-progress', courseId], networkMode: 'always', queryFn: async () => {
    try { return await learnerApi.progress(courseId) } catch (error) { if (error instanceof ApiError && [401, 403].includes(error.status)) throw error; if (await getOfflinePackage(courseId)) return []; throw error instanceof Error ? error : new Error('Не удалось загрузить прогресс.') }
  } })
  const offlineInfo = useQuery({ queryKey: ['learner-offline-manifest', courseId], queryFn: () => learnerApi.offlineManifest(courseId), enabled: online && Boolean(course.data?.snapshot) })
  const save = useMutation({ mutationFn: ({ id, percent }: { id: string; percent: number }) => learnerApi.saveProgress(courseId, id, percent), onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['learner-progress', courseId] }) } })
  const snapshot = course.data?.snapshot
  const activeLessonId = snapshot && progress.data ? lessonId ?? continuationLesson(snapshot, progress.data) : null
  const lesson = snapshot?.modules.flatMap((module) => module.lessons).find((item) => item.id === activeLessonId)
  const lessonProgress = progress.data?.find((row) => row.lesson_id === lesson?.id)
  useEffect(() => {
    setOfflinePackageLoaded(false)
    void getOfflinePackage(courseId)
      .then(setOfflinePackage)
      .finally(() => { setOfflinePackageLoaded(true) })
  }, [courseId])
  useEffect(() => {
    if (online) void syncOfflineCourse(courseId).then(setOfflinePackage).catch(() => { void getOfflinePackage(courseId).then(setOfflinePackage) })
  }, [courseId, online])
  useEffect(() => {
    if (online && lesson && lesson.id !== recordedLessonId && lessonProgress?.status !== 'completed') {
      setRecordedLessonId(lesson.id)
      save.mutate({ id: lesson.id, percent: Math.max(1, lessonProgress?.percent ?? 0) })
    }
  }, [lesson, lessonProgress, online, recordedLessonId, save])
  if (course.isLoading || progress.isLoading) return <main className="loading-screen">Загрузка курса...</main>
  const requestError = course.error ?? progress.error
  if (requestError instanceof ApiError && requestError.code === 'SESSION_REVOKED') return <main className="state-screen"><h1>Сессия открыта на другом устройстве</h1><p>Доступ открыт на другом устройстве. Откройте ссылку там, где хотите продолжить обучение.</p></main>
  if (course.isError || progress.isError || !course.data?.snapshot || !progress.data) return <main className="state-screen"><h1>Курс недоступен</h1><p>Доступ отозван или курс больше не опубликован.</p><button className="text-button" onClick={onBack}>Вернуться к курсам</button></main>
  const currentSnapshot = course.data.snapshot
  const snapshotLoadedOffline = course.data.loadedFromOffline
  const offlineAssetIds = new Set(offlinePackage?.assets.map((asset) => asset.id) ?? [])
  const watermark = `${currentSnapshot.viewer.email} · ${currentSnapshot.viewer.session_id}`
  const offlineAllowed = currentSnapshot.modules.some((module) => module.lessons.some((item) => item.content_units.some((unit) => unit.type === 'text' || unit.is_downloadable === true)))
  const startDownload = () => {
    const controller = new AbortController()
    downloadController.current = controller
    setDownloadError(''); setIsDownloading(true); setDownloadProgress(0)
    void downloadOfflineCourse(courseId, (loaded, total) => { setDownloadSize(total); setDownloadProgress(total ? Math.round(loaded / total * 100) : 0) }, controller.signal)
      .then((value) => { setOfflinePackage(value) })
      .catch((error: unknown) => { if (!(error instanceof DOMException && error.name === 'AbortError')) setDownloadError(error instanceof Error ? error.message : 'Не удалось скачать курс.') })
      .finally(() => { setIsDownloading(false); downloadController.current = null })
  }
  const removeDownload = () => { void deleteOfflineCourse(courseId).then(() => { setOfflinePackage(undefined); setDownloadProgress(0); setDownloadSize(0) }) }
  return <main className="learner-shell"><header className="workspace-header"><div><button className="text-button back-button" onClick={onBack}>← Все курсы</button><p className="eyebrow">Ваш учебный маршрут</p><h1>{currentSnapshot.title}</h1></div></header><div className="offline-manager">{!offlinePackageLoaded && <span>Проверяем загрузки…</span>}{offlinePackageLoaded && offlineAllowed && !offlinePackage && !isDownloading && <><button className="primary-action" disabled={!online} onClick={startDownload}>Скачать курс</button>{typeof offlineInfo.data?.total_size === 'number' && <span>{formatBytes(offlineInfo.data.total_size)}</span>}</>}{isDownloading && <><p>Загрузка: {downloadProgress}% · {formatBytes(downloadSize)}</p><progress max="100" value={downloadProgress}>{downloadProgress}%</progress><button onClick={() => { downloadController.current?.abort() }}>Отменить загрузку</button></>}{offlinePackage && <><strong>Доступно офлайн</strong><span>{formatBytes(offlinePackage.totalSize)}</span>{offlinePackage.updateAvailable && <><span className="status">Доступно обновление</span><button disabled={!online || isDownloading} onClick={startDownload}>Обновить скачанный курс</button></>}<button onClick={removeDownload}>Удалить с устройства</button></>}{downloadError && <p className="form-error">{downloadError}</p>}</div><div className="learner-grid"><nav className="lesson-nav"><p className="eyebrow">Содержание</p>{currentSnapshot.modules.map((module) => <div key={module.id}><h3>{module.title}</h3>{module.lessons.map((item) => { const done = progress.data.find((row) => row.lesson_id === item.id)?.status === 'completed'; return <button className={item.id === lesson?.id ? 'lesson-link active' : 'lesson-link'} key={item.id} onClick={() => { setLessonId(item.id) }}><span>{done ? '✓ ' : ''}{item.title}</span></button> })}</div>)}</nav><article className="lesson-view"><p className="eyebrow">Урок</p><h2>{lesson?.title ?? 'Выберите урок'}</h2><p className="muted">{lesson?.description}</p>{lesson?.content_units.map((unit) => <div className="content-unit" key={unit.id}>{unit.type === 'text' ? <div className="markdown-content"><Markdown text={unit.text_markdown ?? ''} /></div> : <MediaUnit courseId={courseId} unit={unit} watermark={watermark} offlinePackage={offlinePackage} offlineAssetAvailable={offlineAssetIds.has(unit.media_asset_id ?? '') || (Boolean(offlinePackage) && !online && unit.is_downloadable === true) || (snapshotLoadedOffline && unit.is_downloadable === true)} snapshotLoadedOffline={snapshotLoadedOffline} />}</div>)}{lesson && <button className="primary-action" disabled={!online} onClick={() => { save.mutate({ id: lesson.id, percent: 100 }) }}>Отметить урок завершённым ✓</button>}</article></div></main>
}

function CourseCover({ course }: { course: LearnerCourse }) {
  const cover = useQuery({ queryKey: ['learner-cover', course.id, course.cover_asset_id], queryFn: () => learnerApi.streamUrl(course.id, course.cover_asset_id ?? ''), enabled: Boolean(course.cover_asset_id) })
  if (cover.data) return <img className="learner-course-cover" src={cover.data.url} alt="" />
  return <div className="learner-course-cover cover-placeholder" aria-hidden="true">{course.title.slice(0, 1).toUpperCase()}</div>
}

function CourseCatalog({ courses, standalone, onSelect, onLogout }: { courses: LearnerCourse[]; standalone: boolean; onSelect: (id: string) => void; onLogout: () => void }) {
  const progressQueries = useQueries({ queries: courses.map((course) => ({ queryKey: ['learner-progress', course.id], queryFn: () => learnerApi.progress(course.id) })) })
  return <main className="learner-shell"><header className="workspace-header"><div><p className="eyebrow">Кабинет ученика</p><h1>Все курсы</h1></div><button className="text-button" onClick={onLogout}>Выйти</button></header>{!standalone && <TransferPanel />}<section className="learner-catalog"><div className="catalog-heading"><h2>Ваши учебные маршруты</h2><p className="muted">Выберите курс. Мы продолжим с последнего незавершенного урока.</p></div>{courses.length === 0 ? <p className="empty-state">Активных курсов пока нет.</p> : <div className="learner-course-list">{courses.map((course, index) => { const rows = progressQueries[index]?.data ?? []; const completed = rows.filter((row) => row.status === 'completed').length; return <button className="learner-course-card" key={course.id} onClick={() => { onSelect(course.id) }}><CourseCover course={course} /><span className="course-card-copy"><span className="status">{completed > 0 ? `${String(completed)} уроков завершено` : 'Можно начинать'}</span><strong>{course.title}</strong><small>{course.short_description || 'Откройте курс, чтобы увидеть программу.'}</small><span className="course-card-link">Продолжить →</span></span></button> })}</div>}</section></main>
}

export function LearnerPage() {
  const [courseId, setCourseId] = useState<string | null>(null)
  const [accessToken, setAccessToken] = useState<string | null>(null)
  const [locationReady, setLocationReady] = useState(false)
  const [authEpoch, setAuthEpoch] = useState(0)
  const queryClient = useQueryClient()
  const serviceWorkerReady = useServiceWorkerReady()
  const standalone = useStandaloneMode()
  useEffect(() => {
    const token = takeAccessTokenFromLocation()
    if (token) setAccessToken(token)
    setLocationReady(true)
  }, [])
  const existingCourses = useQuery({ queryKey: ['learner-courses', authEpoch], networkMode: 'always', queryFn: async () => {
    try { return await learnerApi.courses() } catch (error) { if (error instanceof ApiError && [401, 403].includes(error.status)) throw error; const local = await listOfflineCourses(); if (local.length) return local; throw error instanceof Error ? error : new Error('Не удалось загрузить курсы.') }
  }, enabled: locationReady && !courseId && !accessToken })
  const logout = useMutation({ mutationFn: async () => { try { return await learnerApi.logout() } finally { await deleteAllOfflineCourses().catch(() => undefined) } }, onSuccess: () => { queryClient.clear(); setCourseId(null) } })
  useEffect(() => {
    const sync = () => { void syncOfflineCourses().catch(() => undefined) }
    if (navigator.onLine) sync()
    window.addEventListener('online', sync)
    return () => { window.removeEventListener('online', sync) }
  }, [])
  const completeSessionChange = async (nextCourseId: string | null, purgeOffline: boolean) => {
    queryClient.clear()
    window.history.replaceState({}, '', '/app/')
    if (purgeOffline) await deleteAllOfflineCourses().catch(() => undefined)
    setAccessToken(null)
    setCourseId(nextCourseId)
    setAuthEpoch((value) => value + 1)
  }
  const serviceWorkerStatus = <p className={serviceWorkerReady ? 'form-success' : 'muted'}>{serviceWorkerReady ? 'Офлайн-функции готовы' : 'Для офлайн-просмотра перезапустите приложение'}</p>
  if (!locationReady) return <main className="loading-screen">Проверяем сессию...</main>
  if (!courseId && accessToken) return <>{serviceWorkerStatus}<AccessLogin token={accessToken} onLogin={(id) => completeSessionChange(id, true)} /></>
  if (courseId) return <>{serviceWorkerStatus}<CourseView courseId={courseId} onBack={() => { setCourseId(null) }} /></>
  if (existingCourses.isLoading) return <main className="loading-screen">Проверяем сессию...</main>
  if (existingCourses.error instanceof ApiError && existingCourses.error.code === 'SESSION_REVOKED') return <main className="state-screen"><h1>Сессия открыта на другом устройстве</h1><p>Доступ открыт на другом устройстве. Откройте ссылку там, где хотите продолжить обучение.</p></main>
  if (existingCourses.isError) return standalone ? <PwaTransferLogin onAuthenticated={() => completeSessionChange(null, true)} /> : <main className="state-screen"><h1>Откройте ссылку из письма</h1><p>Для входа в кабинет ученика нужна персональная ссылка доступа.</p></main>
  return <>{serviceWorkerStatus}<CourseCatalog courses={existingCourses.data ?? []} standalone={standalone} onSelect={setCourseId} onLogout={() => { logout.mutate() }} /></>
}
