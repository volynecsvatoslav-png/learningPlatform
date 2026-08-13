import { useEffect, useState } from 'react'
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, learnerApi, type ContentUnit, type LearnerCourse, type LearnerProgress, type LearnerSnapshot } from '../lib/api'

function Markdown({ text }: { text: string }) {
  return <>{text.split('\n').map((line, index) => {
    if (line.startsWith('# ')) return <h2 key={index}>{line.slice(2)}</h2>
    if (line.startsWith('## ')) return <h3 key={index}>{line.slice(3)}</h3>
    return <p key={index}>{line || '\u00a0'}</p>
  })}</>
}

function AccessLogin({ token, onLogin }: { token: string; onLogin: (courseId: string) => void }) {
  const access = useQuery({ queryKey: ['access-link', token], queryFn: () => learnerApi.access(token) })
  const login = useMutation({ mutationFn: () => learnerApi.login(token), onSuccess: (data) => { window.history.replaceState({}, '', '/app/'); onLogin(data.course_id) } })
  if (access.isLoading) return <main className="loading-screen">Проверяем ссылку...</main>
  if (access.isError || !access.data) return <main className="state-screen"><h1>Доступ отозван</h1><p>Эта ссылка больше недействительна. Попросите вендора перевыпустить доступ.</p></main>
  return <main className="auth-layout"><section className="auth-card"><p className="eyebrow">Вход ученика</p><h1>{access.data.course_title}</h1><p className="muted">Ссылка предназначена для {access.data.email}. На новом устройстве предыдущая сессия будет закрыта.</p><button className="primary-action" onClick={() => { login.mutate() }}>Открыть курс <span aria-hidden="true">→</span></button>{login.error && <p className="form-error">Ссылка больше недействительна.</p>}</section></main>
}

function MediaUnit({ courseId, unit }: { courseId: string; unit: ContentUnit }) {
  const media = useQuery({ queryKey: ['learner-media', courseId, unit.media_asset_id], queryFn: () => learnerApi.streamUrl(courseId, unit.media_asset_id ?? ''), enabled: Boolean(unit.media_asset_id) })
  if (media.isLoading) return <p className="muted">Готовим воспроизведение...</p>
  if (media.isError || !media.data) return <p className="form-error">Медиа недоступно.</p>
  if (unit.type === 'image') return <img className="lesson-image" src={media.data.url} alt={unit.title} />
  if (unit.type === 'audio') return <audio controls src={media.data.url} />
  return <video controls src={media.data.url} />
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
  const queryClient = useQueryClient()
  const course = useQuery({ queryKey: ['learner-course', courseId], queryFn: () => learnerApi.course(courseId) })
  const progress = useQuery({ queryKey: ['learner-progress', courseId], queryFn: () => learnerApi.progress(courseId) })
  const save = useMutation({ mutationFn: ({ id, percent }: { id: string; percent: number }) => learnerApi.saveProgress(courseId, id, percent), onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['learner-progress', courseId] }) } })
  const snapshot = course.data
  const activeLessonId = snapshot && progress.data ? lessonId ?? continuationLesson(snapshot, progress.data) : null
  const lesson = snapshot?.modules.flatMap((module) => module.lessons).find((item) => item.id === activeLessonId)
  const lessonProgress = progress.data?.find((row) => row.lesson_id === lesson?.id)
  useEffect(() => {
    if (lesson && lesson.id !== recordedLessonId && lessonProgress?.status !== 'completed') {
      setRecordedLessonId(lesson.id)
      save.mutate({ id: lesson.id, percent: Math.max(1, lessonProgress?.percent ?? 0) })
    }
  }, [lesson, lessonProgress, recordedLessonId, save])
  if (course.isLoading || progress.isLoading) return <main className="loading-screen">Загрузка курса...</main>
  const requestError = course.error ?? progress.error
  if (requestError instanceof ApiError && requestError.code === 'SESSION_REVOKED') return <main className="state-screen"><h1>Сессия открыта на другом устройстве</h1><p>Доступ открыт на другом устройстве. Откройте ссылку там, где хотите продолжить обучение.</p></main>
  if (course.isError || progress.isError || !course.data || !progress.data) return <main className="state-screen"><h1>Курс недоступен</h1><p>Доступ отозван или курс больше не опубликован.</p><button className="text-button" onClick={onBack}>Вернуться к курсам</button></main>
  const currentSnapshot = course.data
  return <main className="learner-shell"><header className="workspace-header"><div><button className="text-button back-button" onClick={onBack}>← Все курсы</button><p className="eyebrow">Ваш учебный маршрут</p><h1>{currentSnapshot.title}</h1></div></header><div className="learner-grid"><nav className="lesson-nav"><p className="eyebrow">Содержание</p>{currentSnapshot.modules.map((module) => <div key={module.id}><h3>{module.title}</h3>{module.lessons.map((item) => { const done = progress.data.find((row) => row.lesson_id === item.id)?.status === 'completed'; return <button className={item.id === lesson?.id ? 'lesson-link active' : 'lesson-link'} key={item.id} onClick={() => { setLessonId(item.id) }}><span>{done ? '✓ ' : ''}{item.title}</span></button> })}</div>)}</nav><article className="lesson-view"><p className="eyebrow">Урок</p><h2>{lesson?.title ?? 'Выберите урок'}</h2><p className="muted">{lesson?.description}</p>{lesson?.content_units.map((unit) => <div className="content-unit" key={unit.id}>{unit.type === 'text' ? <div className="markdown-content"><Markdown text={unit.text_markdown ?? ''} /></div> : <MediaUnit courseId={courseId} unit={unit} />}</div>)}{lesson && <button className="primary-action" onClick={() => { save.mutate({ id: lesson.id, percent: 100 }) }}>Отметить урок завершённым ✓</button>}</article></div></main>
}

function CourseCover({ course }: { course: LearnerCourse }) {
  const cover = useQuery({ queryKey: ['learner-cover', course.id, course.cover_asset_id], queryFn: () => learnerApi.streamUrl(course.id, course.cover_asset_id ?? ''), enabled: Boolean(course.cover_asset_id) })
  if (cover.data) return <img className="learner-course-cover" src={cover.data.url} alt="" />
  return <div className="learner-course-cover cover-placeholder" aria-hidden="true">{course.title.slice(0, 1).toUpperCase()}</div>
}

function CourseCatalog({ courses, onSelect, onLogout }: { courses: LearnerCourse[]; onSelect: (id: string) => void; onLogout: () => void }) {
  const progressQueries = useQueries({ queries: courses.map((course) => ({ queryKey: ['learner-progress', course.id], queryFn: () => learnerApi.progress(course.id) })) })
  return <main className="learner-shell"><header className="workspace-header"><div><p className="eyebrow">Кабинет ученика</p><h1>Все курсы</h1></div><button className="text-button" onClick={onLogout}>Выйти</button></header><section className="learner-catalog"><div className="catalog-heading"><h2>Ваши учебные маршруты</h2><p className="muted">Выберите курс. Мы продолжим с последнего незавершенного урока.</p></div><div className="learner-course-list">{courses.map((course, index) => { const rows = progressQueries[index]?.data ?? []; const completed = rows.filter((row) => row.status === 'completed').length; return <button className="learner-course-card" key={course.id} onClick={() => { onSelect(course.id) }}><CourseCover course={course} /><span className="course-card-copy"><span className="status">{completed > 0 ? `${String(completed)} уроков завершено` : 'Можно начинать'}</span><strong>{course.title}</strong><small>{course.short_description || 'Откройте курс, чтобы увидеть программу.'}</small><span className="course-card-link">Продолжить →</span></span></button> })}</div></section></main>
}

export function LearnerPage() {
  const [courseId, setCourseId] = useState<string | null>(null)
  const queryClient = useQueryClient()
  const token = window.location.pathname.split('/').filter(Boolean).at(-1)
  const hasAccessToken = Boolean(token && token !== 'app')
  const existingCourses = useQuery({ queryKey: ['learner-courses'], queryFn: learnerApi.courses, enabled: !courseId && !hasAccessToken })
  const logout = useMutation({ mutationFn: learnerApi.logout, onSuccess: () => { queryClient.clear(); setCourseId(null) } })
  if (!courseId && hasAccessToken && token) return <AccessLogin token={token} onLogin={setCourseId} />
  if (courseId) return <CourseView courseId={courseId} onBack={() => { setCourseId(null) }} />
  if (existingCourses.isLoading) return <main className="loading-screen">Проверяем сессию...</main>
  if (existingCourses.error instanceof ApiError && existingCourses.error.code === 'SESSION_REVOKED') return <main className="state-screen"><h1>Сессия открыта на другом устройстве</h1><p>Доступ открыт на другом устройстве. Откройте ссылку там, где хотите продолжить обучение.</p></main>
  if (existingCourses.isError || !existingCourses.data?.length) return <main className="state-screen"><h1>Откройте ссылку из письма</h1><p>Для входа в кабинет ученика нужна персональная ссылка доступа.</p></main>
  return <CourseCatalog courses={existingCourses.data} onSelect={setCourseId} onLogout={() => { logout.mutate() }} />
}
