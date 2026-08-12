import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { LandingPage } from './landing-page'

describe('LandingPage', () => {
  it('показывает ссылку на серверную панель управления', () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <LandingPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(
      screen.getByRole('heading', {
        name: 'Знания, собранные в ясный маршрут.',
      }),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /открыть кабинет вендора/i })).toHaveAttribute(
      'href',
      '/vendor/',
    )
    expect(screen.queryByText(/скачать курс/i)).not.toBeInTheDocument()
  })
})
