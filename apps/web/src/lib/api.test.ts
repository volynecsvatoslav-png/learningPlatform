import { afterEach, describe, expect, it, vi } from 'vitest'


describe('learner session transfer API', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.resetModules()
  })

  it('uses learner CSRF and keeps the transfer code out of the URL', async () => {
    const calls: Array<{ url: string; options?: RequestInit }> = []
    vi.stubGlobal('fetch', vi.fn<typeof fetch>((input, options) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
      calls.push({ url, options })
      if (url === '/api/v1/learner/csrf') {
        return Promise.resolve(new Response(JSON.stringify({ csrfToken: 'learner-csrf' })))
      }
      return Promise.resolve(new Response(JSON.stringify({ ok: true })))
    }))
    const { learnerApi } = await import('./api')

    await learnerApi.consumePwaTransfer('one-time-secret-code')

    expect(calls.map((call) => call.url)).toEqual([
      '/api/v1/learner/csrf',
      '/api/v1/learner/pwa-transfer/consume',
    ])
    expect(calls.some((call) => call.url.includes('one-time-secret-code'))).toBe(false)
    expect(calls[1]?.options?.body).toBe(JSON.stringify({ code: 'one-time-secret-code' }))
    expect(new Headers(calls[1]?.options?.headers).get('X-CSRFToken')).toBe('learner-csrf')
    expect(calls[1]?.options?.cache).toBe('no-store')
  })
})
