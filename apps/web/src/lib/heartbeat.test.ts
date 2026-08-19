import { ApiError, learnerApi, resetCsrfTokens } from './api'
import { ensureFreshHeartbeat, HEARTBEAT_REUSE_MS, resetHeartbeatCache } from './heartbeat'

describe('heartbeat coordinator', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    resetHeartbeatCache()
    resetCsrfTokens()
  })

  it('reuses a recent successful heartbeat without a second request', async () => {
    const spy = vi.spyOn(learnerApi, 'heartbeat').mockResolvedValue({ generation: 1, expires_at: null })

    await ensureFreshHeartbeat()
    await ensureFreshHeartbeat()

    expect(spy).toHaveBeenCalledTimes(1)
  })

  it('coalesces concurrent heartbeats into a single request', async () => {
    const spy = vi.spyOn(learnerApi, 'heartbeat').mockResolvedValue({ generation: 1, expires_at: null })

    await Promise.all([ensureFreshHeartbeat(), ensureFreshHeartbeat(), ensureFreshHeartbeat()])

    expect(spy).toHaveBeenCalledTimes(1)
  })

  it('refetches when the cached heartbeat is older than the reuse window', async () => {
    const spy = vi.spyOn(learnerApi, 'heartbeat').mockResolvedValue({ generation: 1, expires_at: null })

    await ensureFreshHeartbeat()
    await ensureFreshHeartbeat(-1)

    expect(spy).toHaveBeenCalledTimes(2)
  })

  it('does not cache a rejected heartbeat and retries it on the next call', async () => {
    const spy = vi.spyOn(learnerApi, 'heartbeat')
      .mockRejectedValueOnce(new ApiError(401, 'SESSION_REPLACED'))
      .mockResolvedValue({ generation: 1, expires_at: null })

    await expect(ensureFreshHeartbeat()).rejects.toMatchObject({ status: 401 })
    await ensureFreshHeartbeat()

    expect(spy).toHaveBeenCalledTimes(2)
  })

  it('stops reusing the previous session heartbeat after a reset', async () => {
    const spy = vi.spyOn(learnerApi, 'heartbeat').mockResolvedValue({ generation: 1, expires_at: null })

    await ensureFreshHeartbeat()
    resetHeartbeatCache()
    await ensureFreshHeartbeat()

    expect(spy).toHaveBeenCalledTimes(2)
  })

  it('exposes a five-second reuse window', () => {
    expect(HEARTBEAT_REUSE_MS).toBe(5_000)
  })
})