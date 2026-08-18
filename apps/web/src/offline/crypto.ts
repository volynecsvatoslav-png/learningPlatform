import type { OfflineLicenseClaims } from './types'
import { OFFLINE_LICENSE_PUBLIC_JWK } from './license-key'

const encoder = new TextEncoder()

function decodeBase64Url(value: string): Uint8Array<ArrayBuffer> {
  const normalized = value.replace(/-/g, '+').replace(/_/g, '/')
  const binary = atob(normalized.padEnd(Math.ceil(normalized.length / 4) * 4, '='))
  return Uint8Array.from(binary, (character) => character.charCodeAt(0))
}

export function chunkAad(courseId: string, revisionId: string, assetId: string, index: number): Uint8Array<ArrayBuffer> {
  return encoder.encode(`${courseId}:${revisionId}:${assetId}:${String(index)}`)
}

export async function createOfflineKey(): Promise<CryptoKey> {
  return crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt'])
}

export async function encryptChunk(key: CryptoKey, plain: BufferSource, aad: BufferSource): Promise<{ iv: ArrayBuffer; ciphertext: ArrayBuffer }> {
  const iv = crypto.getRandomValues(new Uint8Array(12))
  const ciphertext = await crypto.subtle.encrypt({ name: 'AES-GCM', iv, additionalData: aad }, key, plain)
  return { iv: iv.buffer, ciphertext }
}

export async function decryptChunk(key: CryptoKey, ciphertext: BufferSource, iv: BufferSource, aad: BufferSource): Promise<ArrayBuffer> {
  return crypto.subtle.decrypt({ name: 'AES-GCM', iv, additionalData: aad }, key, ciphertext)
}

export function decodeLicenseClaims(token: string): OfflineLicenseClaims {
  const parts = token.split('.')
  if (parts.length !== 3) throw new Error('OFFLINE_LICENSE_INVALID')
  const payload = parts[1]
  if (!payload) throw new Error('OFFLINE_LICENSE_INVALID')
  return JSON.parse(new TextDecoder().decode(decodeBase64Url(payload))) as OfflineLicenseClaims
}

export async function verifyOfflineLicense(token: string, expected: { courseId: string; revisionId: string; learnerId?: string; deviceId?: string; accessPassId?: string; passGeneration?: number }, now = Date.now()): Promise<OfflineLicenseClaims> {
  const parts = token.split('.')
  if (parts.length !== 3) throw new Error('OFFLINE_LICENSE_INVALID')
  const [header, payload, signature] = parts
  if (!header || !payload || !signature) throw new Error('OFFLINE_LICENSE_INVALID')
  const protectedHeader = JSON.parse(new TextDecoder().decode(decodeBase64Url(header))) as { alg?: unknown }
  if (protectedHeader.alg !== 'ES256') throw new Error('OFFLINE_LICENSE_INVALID')
  const key = await crypto.subtle.importKey('jwk', OFFLINE_LICENSE_PUBLIC_JWK, { name: 'ECDSA', namedCurve: 'P-256' }, false, ['verify'])
  const valid = await crypto.subtle.verify(
    { name: 'ECDSA', hash: 'SHA-256' },
    key,
    decodeBase64Url(signature),
    encoder.encode(`${header}.${payload}`),
  )
  if (!valid) throw new Error('OFFLINE_LICENSE_INVALID')
  const claims = decodeLicenseClaims(token)
  const issuedAt = claims.iat * 1000
  if (!Number.isSafeInteger(claims.iat) || issuedAt > now + 5 * 60 * 1000) throw new Error('OFFLINE_LICENSE_INVALID')
  if (claims.expires_at * 1000 <= now) throw new Error('OFFLINE_LICENSE_EXPIRED')
  if (claims.exp !== claims.expires_at || claims.issued_at !== claims.iat) throw new Error('OFFLINE_LICENSE_INVALID')
  if (!claims.learner_id || !claims.device_id || !claims.access_pass_id) throw new Error('OFFLINE_LICENSE_INVALID')
  if (claims.course_id !== expected.courseId || claims.revision_id !== expected.revisionId) throw new Error('OFFLINE_LICENSE_INVALID')
  if (expected.learnerId && claims.learner_id !== expected.learnerId) throw new Error('OFFLINE_LICENSE_INVALID')
  if (expected.deviceId && claims.device_id !== expected.deviceId) throw new Error('OFFLINE_LICENSE_INVALID')
  if (expected.accessPassId && claims.access_pass_id !== expected.accessPassId) throw new Error('OFFLINE_LICENSE_INVALID')
  if (expected.passGeneration !== undefined && claims.pass_generation !== expected.passGeneration) throw new Error('OFFLINE_LICENSE_INVALID')
  return claims
}
