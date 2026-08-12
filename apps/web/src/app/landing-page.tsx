export function LandingPage() {
  return (
    <div className="site-shell">
      <header className="site-header">
        <a className="brand" href="/" aria-label="Контур, на главную">
          <span className="brand-mark" aria-hidden="true">
            К
          </span>
          <span>Контур</span>
        </a>
          <a className="admin-link" href="/vendor/">
            Кабинет вендора
          <span aria-hidden="true">↗</span>
        </a>
      </header>

      <main className="hero">
        <div className="hero-copy">
          <p className="eyebrow">Обучающая платформа</p>
          <h1>Знания, собранные в ясный маршрут.</h1>
          <p className="intro">
            Пространство для учебных материалов и последовательного обучения.
            Сейчас мы настраиваем основу платформы.
          </p>
          <a className="primary-action" href="/vendor/">
            Открыть кабинет вендора
            <span aria-hidden="true">→</span>
          </a>
          <p className="route-note">
            Платформа администратора доступна только через <code>/backoffice/</code>
          </p>
        </div>

        <aside className="status-card" aria-label="Состояние платформы">
          <div className="card-index" aria-hidden="true">
            01
          </div>
          <div>
            <p className="card-label">Текущий этап</p>
            <h2>Фундамент системы</h2>
            <p>
              Готовим надёжную основу для авторов и администраторов курсов.
            </p>
          </div>
          <div className="status-line">
            <span aria-hidden="true" />
            Система разворачивается
          </div>
        </aside>
      </main>

      <footer className="site-footer">
        <span>Контур / этап 1</span>
        <span>Понятно. Последовательно. Без лишнего.</span>
      </footer>
    </div>
  )
}
