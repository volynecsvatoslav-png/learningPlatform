import type { OfflineLicenseClaims } from './types'

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

export async function verifyOfflineLicense(token: string, verificationKey: JsonWebKey, now = Date.now()): Promise<OfflineLicenseClaims> {
  const parts = token.split('.')
  if (parts.length !== 3) throw new Error('OFFLINE_LICENSE_INVALID')
  const [header, payload, signature] = parts
  if (!header || !payload || !signature) throw new Error('OFFLINE_LICENSE_INVALID')
  const key = await crypto.subtle.importKey('jwk', verificationKey, { name: 'ECDSA', namedCurve: 'P-256' }, false, ['verify'])
  const valid = await crypto.subtle.verify(
    { name: 'ECDSA', hash: 'SHA-256' },
    key,
    decodeBase64Url(signature),
    encoder.encode(`${header}.${payload}`),
  )
  if (!valid) throw new Error('OFFLINE_LICENSE_INVALID')
  const claims = decodeLicenseClaims(token)
  if (claims.expires_at * 1000 <= now) throw new Error('OFFLINE_LICENSE_EXPIRED')
  return claims
}
