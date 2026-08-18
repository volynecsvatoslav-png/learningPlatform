import { afterEach, describe, expect, it, vi } from 'vitest'


describe('learner activation API', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.resetModules()
  })

  it('uses learner CSRF and keeps the access token out of the URL', async () => {
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

    await learnerApi.exchange({ token: 'one-time-access-token', installationId: 'device-1', publicKeyJwk: { kty: 'EC', crv: 'P-256', x: 'x', y: 'y' }, challenge: 'challenge-1', signature: 'signed-challenge', confirmTransfer: true })

    expect(calls.map((call) => call.url)).toEqual([
      '/api/v1/learner/csrf',
      '/api/v1/auth/access/exchange',
    ])
    expect(calls.some((call) => call.url.includes('one-time-access-token'))).toBe(false)
    expect(JSON.parse(calls[1]?.options?.body as string | undefined ?? '{}')).toEqual({
      token: 'one-time-access-token',
      installation_id: 'device-1',
      public_key_jwk: { kty: 'EC', crv: 'P-256', x: 'x', y: 'y' },
      challenge: 'challenge-1',
      signature: 'signed-challenge',
      confirm_transfer: true,
    })
    expect(new Headers(calls[1]?.options?.headers).get('X-CSRFToken')).toBe('learner-csrf')
    expect(calls[1]?.options?.cache).toBe('no-store')
  })

  it('posts the recovery signature without leaking the token into the URL', async () => {
    const calls: Array<{ url: string; options?: RequestInit }> = []
    vi.stubGlobal('fetch', vi.fn<typeof fetch>((input, options) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
      calls.push({ url, options })
      if (url === '/api/v1/learner/csrf') {
        return Promise.resolve(new Response(JSON.stringify({ csrfToken: 'learner-csrf' })))
      }
      return Promise.resolve(new Response(JSON.stringify({ ok: true, access_token: 'fresh-token', access_link: 'https://learning.example/app/#access=fresh-token' })))
    }))
    const { learnerApi } = await import('./api')

    const result = await learnerApi.recoveryExchange({ recoveryToken: 'recovery-secret', installationId: 'device-1', publicKeyJwk: { kty: 'EC', crv: 'P-256', x: 'x', y: 'y' }, signature: 'signed-recovery' })

    expect(result.access_token).toBe('fresh-token')
    expect(calls.map((call) => call.url)).toEqual([
      '/api/v1/learner/csrf',
      '/api/v1/auth/recovery/exchange',
    ])
    expect(calls.some((call) => call.url.includes('recovery-secret'))).toBe(false)
    expect(JSON.parse(calls[1]?.options?.body as string | undefined ?? '{}')).toMatchObject({
      recovery_token: 'recovery-secret',
      installation_id: 'device-1',
      signature: 'signed-recovery',
    })
  })
})