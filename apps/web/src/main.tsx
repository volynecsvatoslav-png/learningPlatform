import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider } from 'react-router-dom'
import { QueryProvider } from './app/query-provider'
import { router } from './app/router'
import './styles.css'

const rootElement = document.getElementById('root')

if (!rootElement) {
  throw new Error('Не найден корневой элемент приложения')
}

const serviceWorkerEnabled = import.meta.env.PROD || import.meta.env.VITE_ENABLE_SERVICE_WORKER === 'true'

if ('serviceWorker' in navigator && serviceWorkerEnabled) {
  const workerURL = new URL('/sw.js', window.location.origin)
  workerURL.searchParams.set('licenseKey', import.meta.env.VITE_OFFLINE_LICENSE_PUBLIC_JWK)
  void navigator.serviceWorker.register(`${workerURL.pathname}${workerURL.search}`)
}

createRoot(rootElement).render(
  <StrictMode>
    <QueryProvider>
      <RouterProvider router={router} />
    </QueryProvider>
  </StrictMode>,
)
