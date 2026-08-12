import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, learnerApi, type ContentUnit, type LearnerSnapshot } from '../lib/api'

function markdown(text: string) {
  return text.split('\n').map((line) => {
    if (line.startsWith('# ')) return <h2 key={line}>{line.slice(2)}</h2>
    if (line.startsWith('## ')) return <h3 key={line}>{line.slice(3)}</h3>
    return <p key={line}>{line || '\u00a0'}</p>
  })
}

function AccessLogin({ token, onLogin }: { token: string; onLogin: (courseId: string) => void }) {
  const access = useQuery({ queryKey: ['access-link', token], queryFn: () => learnerApi.access(token) })
  const login = useMutation({ mutationFn: () => learnerApi.login(token), onSuccess: (data) => { window.history.replaceState({}, '', '/app/'); onLogin(data.course_id); } })
  if (access.isLoading) return <main className="loading-screen">Проверяем ссылку...</main>
  if (access.isError || !access.data) return <main className="state-screen"><h1>Доступ отозван</h1><p>Эта ссылка больше недействительна. Попросите вендора перевыпустить доступ.</p></main>
  return <main className="auth-layout"><section className="auth-card"><p className="eyebrow">Вход ученика</p><h1>{access.data.course_title}</h1><p className="muted">Ссылка предназначена для {access.data.email}. На новом устройстве предыдущая сессия будет закрыта.</p><button className="primary-action" onClick={() => { login.mutate(); }}>Открыть курс <span aria-hidden="true">→</span></button>{login.error && <p className="form-error">Ссылка больше недействительна.</p>}</section></main>
}

function MediaUnit({ courseId, unit }: { courseId: string; unit: ContentUnit }) {
  const media = useQuery({ queryKey: ['learner-media', courseId, unit.media_asset_id], queryFn: () => learnerApi.streamUrl(courseId, unit.media_asset_id ?? ''), enabled: Boolean(unit.media_asset_id) })
  if (media.isLoading) return <p className="muted">Готовим воспроизведение...</p>
  if (media.isError || !media.data) return <p className="form-error">Медиа недоступно.</p>
  if (unit.type === 'image') return <img className="lesson-image" src={media.data.url} alt={unit.title} />
  if (unit.type === 'audio') return <audio controls src={media.data.url} />
  return <video controls src={media.data.url} />
}

function CourseView({ courseId, onLogout }: { courseId: string; onLogout: () => void }) {
  const [lessonId, setLessonId] = useState<string | null>(null)
  const queryClient = useQueryClient()
  const course = useQuery({ queryKey: ['learner-course', courseId], queryFn: () => learnerApi.course(courseId) })
  const progress = useQuery({ queryKey: ['learner-progress', courseId], queryFn: () => learnerApi.progress(courseId) })
  const save = useMutation({ mutationFn: ({ id, percent }: { id: string; percent: number }) => learnerApi.saveProgress(courseId, id, percent), onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['learner-progress', courseId] }) } })
  const logout = useMutation({ mutationFn: learnerApi.logout, onSuccess: () => { queryClient.clear(); onLogout() } })
  useEffect(() => {
    const first = course.data?.modules[0]?.lessons[0]?.id
    if (!lessonId && first) setLessonId(first)
  }, [course.data, lessonId])
  if (course.isLoading) return <main className="loading-screen">Загрузка курса...</main>
  if (course.error instanceof ApiError && course.error.code === 'SESSION_REVOKED') return <main className="state-screen"><h1>Сессия открыта на другом устройстве</h1><p>Доступ открыт на другом устройстве. Откройте ссылку там, где хотите продолжить обучение.</p></main>
  if (course.isError || !course.data) return <main className="state-screen"><h1>Курс недоступен</h1><p>Доступ отозван или курс больше не опубликован.</p></main>
  const snapshot: LearnerSnapshot = course.data
  const lesson = snapshot.modules.flatMap((module) => module.lessons).find((item) => item.id === lessonId) ?? snapshot.modules[0]?.lessons[0]
  return <main className="learner-shell"><header className="workspace-header"><div><p className="eyebrow">Ваш учебный маршрут</p><h1>{snapshot.title}</h1></div><button className="text-button" onClick={() => { logout.mutate(); }}>Выйти</button></header><div className="learner-grid"><nav className="lesson-nav"><p className="eyebrow">Содержание</p>{snapshot.modules.map((module) => <div key={module.id}><h3>{module.title}</h3>{module.lessons.map((item) => { const done = progress.data?.find((row) => row.lesson_id === item.id)?.status === 'completed'; return <button className={item.id === lesson?.id ? 'lesson-link active' : 'lesson-link'} key={item.id} onClick={() => { setLessonId(item.id); }}><span>{done ? '✓ ' : ''}{item.title}</span></button> })}</div>)}</nav><article className="lesson-view"><p className="eyebrow">Урок</p><h2>{lesson?.title ?? 'Выберите урок'}</h2><p className="muted">{lesson?.description}</p>{lesson?.content_units.map((unit) => <div className="content-unit" key={unit.id}>{unit.type === 'text' ? <div className="markdown-content">{markdown(unit.text_markdown ?? '')}</div> : <MediaUnit courseId={courseId} unit={unit} />}</div>)}{lesson && <button className="primary-action" onClick={() => { save.mutate({ id: lesson.id, percent: 100 }); }}>Отметить урок завершённым ✓</button>}</article></div></main>
}

export function LearnerPage() {
  const [courseId, setCourseId] = useState<string | null>(null)
  const token = window.location.pathname.split('/').filter(Boolean).at(-1)
  const existingCourses = useQuery({ queryKey: ['learner-courses'], queryFn: learnerApi.courses, enabled: !courseId && (!token || token === 'app') })
  useEffect(() => {
    if (!courseId && existingCourses.data?.[0]) setCourseId(existingCourses.data[0].id)
  }, [courseId, existingCourses.data])
  if (!courseId && token && token !== 'app') return <AccessLogin token={token} onLogin={setCourseId} />
  if (existingCourses.isLoading) return <main className="loading-screen">Проверяем сессию...</main>
  if (existingCourses.error instanceof ApiError && existingCourses.error.code === 'SESSION_REVOKED') return <main className="state-screen"><h1>Сессия открыта на другом устройстве</h1><p>Доступ открыт на другом устройстве. Откройте ссылку там, где хотите продолжить обучение.</p></main>
  if (!courseId) return <main className="state-screen"><h1>Откройте ссылку из письма</h1><p>Для входа в кабинет ученика нужна персональная ссылка доступа.</p></main>
  return <CourseView courseId={courseId} onLogout={() => { setCourseId(null); }} />
}
