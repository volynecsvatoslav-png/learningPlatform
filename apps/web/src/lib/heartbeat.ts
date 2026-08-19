import { learnerApi, type LearnerHeartbeat } from './api'

export const HEARTBEAT_REUSE_MS = 5_000

type HeartbeatCache = { at: number; promise: Promise<LearnerHeartbeat> }

let cached: HeartbeatCache | null = null
let inflight: Promise<LearnerHeartbeat> | null = null

export function ensureFreshHeartbeat(maxAgeMs = HEARTBEAT_REUSE_MS): Promise<LearnerHeartbeat> {
  if (cached && Date.now() - cached.at <= maxAgeMs) return cached.promise
  if (inflight) return inflight
  const request = learnerApi.heartbeat()
  const tracked = request.then((result) => {
    cached = { at: Date.now(), promise: tracked }
    return result
  })
  inflight = tracked
  void tracked.then(
    () => { inflight = null },
    () => { inflight = null },
  )
  return tracked
}

export function resetHeartbeatCache(): void {
  cached = null
  inflight = null
}