import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { VendorPasswordResetPage } from './vendor-password-reset-page'

describe('VendorPasswordResetPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('validates confirmation and submits the password for the URL credentials', async () => {
    window.history.pushState({}, '', '/vendor/reset/user-uid/reset-token')
    const fetchMock = vi.fn<typeof fetch>((input) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
      if (url.endsWith('/api/v1/vendor/csrf')) return Promise.resolve(new Response(JSON.stringify({ csrfToken: 'csrf-token' })))
      return Promise.resolve(new Response(JSON.stringify({ ok: true })))
    })
    vi.stubGlobal('fetch', fetchMock)
    const queryClient = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><VendorPasswordResetPage /></QueryClientProvider>)

    fireEvent.change(screen.getByLabelText('Новый пароль'), { target: { value: 'a sufficiently strong password' } })
    fireEvent.change(screen.getByLabelText('Подтверждение пароля'), { target: { value: 'different strong password' } })
    fireEvent.click(screen.getByRole('button', { name: 'Изменить пароль' }))
    expect(screen.getByText('Пароли не совпадают.')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Подтверждение пароля'), { target: { value: 'a sufficiently strong password' } })
    fireEvent.click(screen.getByRole('button', { name: 'Изменить пароль' }))

    expect(await screen.findByText('Пароль изменен. Теперь можно войти в кабинет.')).toBeInTheDocument()
    await waitFor(() => { expect(fetchMock).toHaveBeenCalledWith('/api/v1/vendor/auth/password-reset/user-uid/reset-token', expect.objectContaining({ method: 'POST' })) })
  })
})
