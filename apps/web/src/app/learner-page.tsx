import { useCallback, useEffect, useRef, useState } from 'react'
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, learnerApi, resetCsrfTokens, type ContentUnit, type LearnerCourse, type LearnerProgress, type LearnerSnapshot } from '../lib/api'
import { getAccessDevice, sha256Hex, type AccessDevice } from '../lib/device-keys'
import { deleteAllOfflineCourses, deleteOfflineCourse, downloadOfflineCourse, formatBytes, getOfflinePackage, listOfflineCourses, offlineMediaUrl, readOfflineSnapshot, syncOfflineCourse, syncOfflineCourses, type OfflinePackage } from '../offline/offline-course'

type EntranceToken = { kind: 'access' | 'recovery'; value: string }
type SessionEndReason = 'replaced' | 'revoked' | 'expired'

function Markdown({ text }: { text: string }) {
  return <>{text.split('\n').map((line, index) => {
    if (line.startsWith('# ')) return <h2 key={index}>{line.slice(2)}</h2>
    if (line.startsWith('## ')) return <h3 key={index}>{line.slice(3)}</h3>
    return <p key={index}>{line || '\u00a0'}</p>
  })}</>
}

function entranceFromLocation(): EntranceToken | null {
  const legacyMatch = /^\/app\/access\/([^/]+)\/?$/.exec(window.location.pathname)
  const fragment = new URLSearchParams(window.location.hash.slice(1))
  const legacyToken = legacyMatch?.[1]
  if (legacyToken) {
    try {
      return { kind: 'access', value: decodeURIComponent(legacyToken) }
    } catch {
      return null
    }
  }
  const access = fragment.get('access')
  if (access) return { kind: 'access', value: access }
  const recovery = fragment.get('recovery')
  if (recovery) return { kind: 'recovery', value: recovery }
  return null
}

function entranceFromPastedLink(value: string): EntranceToken | null {
  try {
    const url = new URL(value.trim())
    if (!['http:', 'https:'].includes(url.protocol)) return null
    const legacyMatch = /^\/app\/access\/([^/]+)\/?$/.exec(url.pathname)
    const legacyToken = legacyMatch?.[1]
    if (legacyToken) {
      try {
        return { kind: 'access', value: decodeURIComponent(legacyToken) }
      } catch {
        return null
      }
    }
    const fragment = new URLSearchParams(url.hash.slice(1))
    const access = fragment.get('access')
    if (access) return { kind: 'access', value: access }
    const recovery = fragment.get('recovery')
    if (recovery) return { kind: 'recovery', value: recovery }
    return null
  } catch {
    return null
  }
}

async function recoverAccessToken(recoveryToken: string): Promise<string> {
  const device = await getAccessDevice()
  const signature = await device.sign(`lms-recovery:${device.installation_id}:${await sha256Hex(recoveryToken)}`)
  const result = await learnerApi.recoveryExchange({ recoveryToken, installationId: device.installation_id, publicKeyJwk: device.public_key_jwk, signature })
  resetCsrfTokens()
  return result.access_token
}

function DeviceActivation({ token, onDone, onCancel }: { token: string; onDone: () => void; onCancel: () => void }) {
  const devicePromise = useRef<Promise<AccessDevice>>(getAccessDevice())
  const confirmTransfer = useRef(false)
  const attempted = useRef(false)
  const [state, setState] = useState<'activating' | 'confirm' | 'error'>('activating')
  const [pending, setPending] = useState(true)
  const [error, setError] = useState('')
  const run = useCallback(async () => {
    setPending(true)
    setError('')
    try {
      const device = await devicePromise.current
      const { challenge } = await learnerApi.inspect(token, device.installation_id, device.public_key_jwk)
      const signature = await device.sign(challenge)
      await learnerApi.exchange({ token, installationId: device.installation_id, publicKeyJwk: device.public_key_jwk, challenge, signature, confirmTransfer: confirmTransfer.current })
      resetCsrfTokens()
      onDone()
    } catch (reason) {
      if (reason instanceof ApiError && reason.code === 'DEVICE_TRANSFER_CONFIRMATION_REQUIRED') {
        confirmTransfer.current = false
        setState('confirm')
        setError('')
        return
      }
      let message = 'Не удалось выполнить вход. Проверьте соединение и повторите попытку.'
      if (reason instanceof ApiError && reason.code === 'INVALID_ACCESS_LINK') message = 'Ссылка больше недействительна. Попросите владельца курса переотправить доступ.'
      if (reason instanceof ApiError && reason.code === 'DEVICE_PROOF_INVALID') message = 'Не удалось подтвердить устройство. Закройте и снова откройте приложение.'
      setState('error')
      setError(message)
    } finally {
      setPending(false)
    }
  }, [token, onDone])
  useEffect(() => { if (!attempted.current) { attempted.current = true; void run() } }, [run])
  if (state === 'confirm') return <main className="auth-layout"><section className="auth-card"><p className="eyebrow">Вход ученика</p><h1>Перенос входа</h1><p className="muted">Доступ уже открыт на другом устройстве. При переносе сессия на том устройстве будет закрыта.</p><button className="primary-action" disabled={pending} onClick={() => { confirmTransfer.current = true; void run() }}>{pending ? 'Переносим…' : 'Перенести вход на это устройство'} <span aria-hidden="true">→</span></button><button className="text-button" disabled={pending} onClick={onCancel}>Отмена</button></section></main>
  if (state === 'error') return <main className="auth-layout"><section className="auth-card"><p className="eyebrow">Вход ученика</p><h1>Не получилось войти</h1><p className="form-error">{error}</p><button className="text-button" onClick={onCancel}>Вернуться</button></section></main>
  return <main className="auth-layout"><section className="auth-card"><p className="eyebrow">Вход ученика</p><h1>Персональный доступ</h1><p className="muted">Настраиваем доступ к вашему устройству…</p>{pending && <p className="pending-indicator">Проверяем ссылку и подписываем запрос</p>}</section></main>
}

function PathAccessLogin({ onAuthenticated }: { onAuthenticated: () => void }) {
  const [link, setLink] = useState('')
  const [accessToken, setAccessToken] = useState<string | null>(null)
  const [recoveryEmail, setRecoveryEmail] = useState('')
  const [recoverySent, setRecoverySent] = useState(false)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const [recoveryError, setRecoveryError] = useState('')
  const submitLink = async () => {
    const entrance = entranceFromPastedLink(link)
    if (!entrance) {
      setError('Вставьте полную ссылку из письма.')
      return
    }
    setPending(true)
    setError('')
    try {
      if (entrance.kind === 'recovery') {
        setAccessToken(await recoverAccessToken(entrance.value))
      } else {
        setAccessToken(entrance.value)
      }
      setLink('')
    } catch {
      setError('Ссылка восстановления недействительна или истекла.')
    } finally {
      setPending(false)
    }
  }
  const requestRecovery = async () => {
    setPending(true)
    setRecoveryError('')
    try {
      await learnerApi.recoveryRequest(recoveryEmail.trim())
      setRecoverySent(true)
    } catch {
      setRecoveryError('Не удалось отправить ссылку восстановления. Попробуйте позже.')
    } finally {
      setPending(false)
    }
  }
  if (accessToken) return <DeviceActivation token={accessToken} onDone={onAuthenticated} onCancel={() => { setAccessToken(null) }} />
  return <main className="auth-layout"><section className="auth-card transfer-login"><p className="eyebrow">Установленное приложение</p><h1>Вход в кабинет ученика</h1><p className="muted">Откройте персональную ссылку из письма или ссылку восстановления доступа.</p><form onSubmit={(event) => { event.preventDefault(); void submitLink() }} autoComplete="off"><label>Полная ссылка из письма<input type="url" value={link} onChange={(event) => { setLink(event.target.value) }} autoComplete="off" spellCheck={false} /></label><button className="primary-action" type="submit" disabled={pending || !link.trim()}>Войти по ссылке</button></form>{error && <p className="form-error">{error}</p>}<details><summary>Восстановить доступ</summary>{!recoverySent ? <><p className="muted">Если приложение было удалено или устройство заменено, мы отправим ссылку восстановления на вашу почту.</p><form onSubmit={(event) => { event.preventDefault(); void requestRecovery() }} autoComplete="off"><label>Email ученика<input type="email" value={recoveryEmail} onChange={(event) => { setRecoveryEmail(event.target.value) }} autoComplete="email" required /></label><button className="text-button" type="submit" disabled={pending || !recoveryEmail.trim()}>Отправить ссылку восстановления</button></form>{recoveryError && <p className="form-error">{recoveryError}</p>}</> : <p className="form-success">Письмо отправлено. Если доступ существует, откройте ссылку из письма.</p>}</details></section></main>
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

function SessionEnded({ reason, onBack, onLogout }: { reason: SessionEndReason; onBack: () => void; onLogout: () => void }) {
  const content = reason === 'replaced'
    ? { title: 'Сессия завершена', text: 'Вход выполнен на другом устройстве. Доступ к этому устройству закрыт.' }
    : reason === 'revoked'
      ? { title: 'Доступ отозван', text: 'Откройте новую ссылку из письма, чтобы продолжить обучение.' }
      : { title: 'Сессия истекла', text: 'Откройте ссылку из письма ещё раз, чтобы продолжить.' }
  return <main className="state-screen"><h1>{content.title}</h1><p>{content.text}</p><div className="state-actions">{reason !== 'replaced' && <button className="primary-action" onClick={onBack}>Вернуться к курсам</button>}<button className="text-button" onClick={onLogout}>Выйти</button></div></main>
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

function sessionEndReason(code: string | undefined): SessionEndReason | null {
  if (code === 'SESSION_REPLACED') return 'replaced'
  if (code === 'SESSION_REVOKED') return 'revoked'
  if (code === 'SESSION_EXPIRED') return 'expired'
  return null
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
  if (requestError instanceof ApiError) {
    const reason = sessionEndReason(requestError.code)
    if (reason) return <SessionEnded reason={reason} onBack={onBack} onLogout={() => { window.dispatchEvent(new Event('lms-logout-request')) }} />
  }
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
  return <main className="learner-shell"><header className="workspace-header"><div><button className="text-button back-button" onClick={onBack}>← Все курсы</button><p className="eyebrow">Ваш учебный маршрут</p><h1>{currentSnapshot.title}</h1></div></header><div className="offline-manager">{!offlinePackageLoaded && <span>Проверяем загрузки…</span>}{offlinePackageLoaded && offlineAllowed && !offlinePackage && !isDownloading && <><button className="primary-action" disabled={!online} onClick={startDownload}>Скачать курс</button>{typeof offlineInfo.data?.total_size === 'number' && <span>{formatBytes(offlineInfo.data.total_size)}</span>}</>}{isDownloading && <><p>Загрузка: {downloadProgress}% · {formatBytes(downloadSize)}</p><progress max="100" value={downloadProgress}>{downloadProgress}%</progress><button onClick={() => { downloadController.current?.abort() }}>Отменить загрузку</button></>}{offlinePackage && <><strong>Доступно офлайн</strong><span>{formatBytes(offlinePackage.totalSize)}</span>{offlinePackage.updateAvailable && <><span className="status">Доступно обновление</span><button disabled={!online || isDownloading} onClick={startDownload}>Обновить скачанный курс</button></>}<button onClick={removeDownload}>Удалить с устройства</button></>}{downloadError && <p className="form-error">{downloadError}</p>}</div><div className="learner-grid"><nav className="lesson-nav"><p className="eyebrow">Содержание</p>{currentSnapshot.modules.map((module) => <div key={module.id}><h3>{module.title}</h3>{module.lessons.map((item) => { const done = progress.data.find((row) => row.lesson_id === item.id)?.status === 'completed'; return <button className={item.id === lesson?.id ? 'lesson-link active' : 'lesson-link'} key={item.id} onClick={() => { setLessonId(item.id) }}><span>{done ? '✓ ' : ''}{item.title}</span></button> })}</div>)}</nav><article className="lesson-view"><p className="eyebrow">Урок</p><h2>{lesson?.title ?? 'Выберите урок'}</h2><p className="muted">{lesson?.description}<br /></p>{lesson && <div className="lesson-content">{lesson.content_units.map((unit) => unit.type === 'text' ? <Markdown key={unit.id} text={unit.text_markdown ?? ''} /> : <MediaUnit key={unit.id} courseId={courseId} unit={unit} watermark={watermark} offlinePackage={offlinePackage} offlineAssetAvailable={offlineAssetIds.has(unit.media_asset_id ?? '')} snapshotLoadedOffline={snapshotLoadedOffline} />)}</div>}</article></div><footer className="learner-footer"><button className="text-button" onClick={() => { window.dispatchEvent(new Event('lms-logout-request')) }}>Выйти</button></footer></main>
}

function CourseCover({ course }: { course: LearnerCourse }) {
  const cover = useQuery({ queryKey: ['learner-cover', course.id, course.cover_asset_id], queryFn: () => learnerApi.streamUrl(course.id, course.cover_asset_id ?? ''), enabled: Boolean(course.cover_asset_id) })
  if (cover.data) return <img className="learner-course-cover" src={cover.data.url} alt="" />
  return <div className="learner-course-cover cover-placeholder" aria-hidden="true">{course.title.slice(0, 1).toUpperCase()}</div>
}

function CourseCatalog({ courses, onSelect, onLogout }: { courses: LearnerCourse[]; onSelect: (id: string) => void; onLogout: () => void }) {
  const progressQueries = useQueries({ queries: courses.map((course) => ({ queryKey: ['learner-progress', course.id], queryFn: () => learnerApi.progress(course.id) })) })
  return <main className="learner-shell"><header className="workspace-header"><div><p className="eyebrow">Кабинет ученика</p><h1>Все курсы</h1></div><button className="text-button" onClick={onLogout}>Выйти</button></header><section className="learner-catalog"><div className="catalog-heading"><h2>Ваши учебные маршруты</h2><p className="muted">Выберите курс. Мы продолжим с последнего незавершенного урока.</p></div>{courses.length === 0 ? <p className="empty-state">Активных курсов пока нет.</p> : <div className="learner-course-list">{courses.map((course, index) => { const rows = progressQueries[index]?.data ?? []; const completed = rows.filter((row) => row.status === 'completed').length; return <button className="learner-course-card" key={course.id} onClick={() => { onSelect(course.id) }}><CourseCover course={course} /><span className="course-card-copy"><span className="status">{completed > 0 ? `${String(completed)} уроков завершено` : 'Можно начинать'}</span><strong>{course.title}</strong><small>{course.short_description || 'Откройте курс, чтобы увидеть программу.'}</small><span className="course-card-link">Продолжить →</span></span></button> })}</div>}</section></main>
}

export function LearnerPage() {
  const [courseId, setCourseId] = useState<string | null>(null)
  const [entrance, setEntrance] = useState<EntranceToken | null>(null)
  const [sessionEnd, setSessionEnd] = useState<SessionEndReason | null>(null)
  const [sessionEndDismissed, setSessionEndDismissed] = useState(false)
  const [locationReady, setLocationReady] = useState(false)
  const [authEpoch, setAuthEpoch] = useState(0)
  const queryClient = useQueryClient()
  const serviceWorkerReady = useServiceWorkerReady()
  const channel = useRef<BroadcastChannel | null>(null)
  useEffect(() => {
    const token = entranceFromLocation()
    if (token) {
      window.history.replaceState({}, '', '/app/')
      setEntrance(token)
    }
    setLocationReady(true)
  }, [])
  useEffect(() => {
    const handleHashChange = () => {
      const token = entranceFromLocation()
      if (token) {
        window.history.replaceState({}, '', '/app/')
        setEntrance(token)
      }
    }
    window.addEventListener('hashchange', handleHashChange)
    return () => { window.removeEventListener('hashchange', handleHashChange) }
  }, [])
  const completeSessionChange = useCallback((nextCourseId: string | null, purgeOffline = false) => {
    queryClient.clear()
    window.history.replaceState({}, '', '/app/')
    if (purgeOffline) void deleteAllOfflineCourses().catch(() => undefined)
    setEntrance(null)
    setSessionEnd(null)
    setSessionEndDismissed(false)
    setCourseId(nextCourseId)
    setAuthEpoch((value) => value + 1)
  }, [queryClient])
  const existingCourses = useQuery({ queryKey: ['learner-courses', authEpoch], networkMode: 'always', queryFn: async () => {
    try { return await learnerApi.courses() } catch (error) { if (error instanceof ApiError && [401, 403].includes(error.status)) throw error; const local = await listOfflineCourses(); if (local.length) return local; throw error instanceof Error ? error : new Error('Не удалось загрузить курсы.') }
  }, enabled: locationReady && !courseId && !entrance })
  const authenticated = !sessionEnd && !sessionEndDismissed && !entrance && (courseId !== null || existingCourses.data !== undefined)
  const heartbeat = useQuery({ queryKey: ['learner-heartbeat', authEpoch], queryFn: learnerApi.heartbeat, enabled: authenticated, refetchInterval: 10_000, networkMode: 'always', retry: false })
  const logout = useMutation({ mutationFn: async () => { try { await learnerApi.logout().catch(() => undefined) } finally { await deleteAllOfflineCourses().catch(() => undefined) } }, onSuccess: () => {
    queryClient.clear()
    window.history.replaceState({}, '', '/app/')
    setEntrance(null)
    setSessionEnd(null)
    setCourseId(null)
    setAuthEpoch((value) => value + 1)
  } })
  useEffect(() => {
    const error = heartbeat.error
    if (error instanceof ApiError && error.status === 401 && !sessionEndDismissed) {
      const reason = sessionEndReason(error.code)
      if (reason) {
        void deleteAllOfflineCourses().catch(() => undefined)
        setSessionEnd(reason)
      }
    }
  }, [heartbeat.error, sessionEndDismissed])
  useEffect(() => {
    if (typeof BroadcastChannel === 'undefined') return
    const broadcast = new BroadcastChannel('lms-access-logout')
    channel.current = broadcast
    broadcast.onmessage = (event) => {
      const data = event.data as { type?: unknown } | null
      if (data?.type === 'logout') completeSessionChange(null, false)
    }
    return () => { broadcast.close(); channel.current = null }
  }, [completeSessionChange])
  const logoutAll = () => {
    setSessionEndDismissed(true)
    try {
      channel.current?.postMessage({ type: 'logout' })
    } catch {
      // BroadcastChannel may be unavailable in some browsers.
    }
    logout.mutate()
  }
  useEffect(() => {
    const handleLogoutRequest = () => { logoutAll() }
    window.addEventListener('lms-logout-request', handleLogoutRequest)
    return () => { window.removeEventListener('lms-logout-request', handleLogoutRequest) }
  })
  useEffect(() => {
    const sync = () => { void syncOfflineCourses().catch(() => undefined) }
    if (navigator.onLine) sync()
    window.addEventListener('online', sync)
    return () => { window.removeEventListener('online', sync) }
  }, [])
  const serviceWorkerStatus = <p className={serviceWorkerReady ? 'form-success' : 'muted'}>{serviceWorkerReady ? 'Офлайн-функции готовы' : 'Для офлайн-просмотра перезапустите приложение'}</p>
  if (!locationReady) return <main className="loading-screen">Проверяем сессию...</main>
  if (entrance?.kind === 'recovery') return <RecoveryEntrance token={entrance.value} onDone={() => { completeSessionChange(null, false) }} onCancel={() => { setEntrance(null) }} />
  if (entrance?.kind === 'access') return <>{serviceWorkerStatus}<DeviceActivation token={entrance.value} onDone={() => { completeSessionChange(null, false) }} onCancel={() => { setEntrance(null) }} /></>
  if (sessionEnd) return <SessionEnded reason={sessionEnd} onBack={() => {
    queryClient.clear()
    setSessionEnd(null)
    setSessionEndDismissed(true)
    setCourseId(null)
    setAuthEpoch((value) => value + 1)
  }} onLogout={logoutAll} />
  if (courseId) return <>{serviceWorkerStatus}<CourseView courseId={courseId} onBack={() => { setCourseId(null) }} /></>
  if (existingCourses.isLoading) return <main className="loading-screen">Проверяем сессию...</main>
  if (existingCourses.isError) {
    const reason = sessionEndReason(existingCourses.error instanceof ApiError ? existingCourses.error.code : undefined)
    if (reason && !sessionEndDismissed) return <SessionEnded reason={reason} onBack={() => {
      queryClient.clear()
      setSessionEndDismissed(true)
      setAuthEpoch((value) => value + 1)
    }} onLogout={logoutAll} />
    return <PathAccessLogin onAuthenticated={() => { completeSessionChange(null, false) }} />
  }
  return <>{serviceWorkerStatus}<CourseCatalog courses={existingCourses.data ?? []} onSelect={setCourseId} onLogout={logoutAll} /></>
}

function RecoveryEntrance({ token, onDone, onCancel }: { token: string; onDone: () => void; onCancel: () => void }) {
  const [accessToken, setAccessToken] = useState<string | null>(null)
  const [pending, setPending] = useState(true)
  const [error, setError] = useState('')
  const attempted = useRef(false)
  useEffect(() => {
    if (attempted.current) return
    attempted.current = true
    const controller = new AbortController()
    void (async () => {
      try {
        setAccessToken(await recoverAccessToken(token))
      } catch {
        if (!controller.signal.aborted) setError('Ссылка восстановления недействительна или истекла.')
      } finally {
        if (!controller.signal.aborted) setPending(false)
      }
    })()
    return () => { controller.abort() }
  }, [token])
  if (accessToken) return <DeviceActivation token={accessToken} onDone={onDone} onCancel={onCancel} />
  if (error) return <main className="auth-layout"><section className="auth-card"><p className="eyebrow">Восстановление доступа</p><h1>Не получилось восстановить доступ</h1><p className="form-error">{error}</p><button className="text-button" onClick={onCancel}>Вернуться</button></section></main>
  return <main className="auth-layout"><section className="auth-card"><p className="eyebrow">Восстановление доступа</p><h1>Восстанавливаем доступ</h1>{pending && <p className="pending-indicator">Подписываем запрос на этом устройстве…</p>}</section></main>
}