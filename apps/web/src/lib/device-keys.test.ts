import { describe, expect, it, afterEach } from 'vitest'
import { getAccessDevice } from './device-keys'

const DB_NAME = 'lms-device'
const STORE = 'credentials'
const RECORD_ID = 'main'

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1)
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(STORE)) request.result.createObjectStore(STORE, { keyPath: 'id' })
    }
    request.onsuccess = () => { resolve(request.result) }
    request.onerror = () => { reject(request.error instanceof Error ? request.error : new Error('DEVICE_KEYS_UNAVAILABLE')) }
  })
}

async function storedCredentials(): Promise<{ installation_id: string; public_key_jwk: JsonWebKey; private_key: CryptoKey } | undefined> {
  const db = await openDb()
  try {
    return await new Promise<{ installation_id: string; public_key_jwk: JsonWebKey; private_key: CryptoKey } | undefined>((resolve, reject) => {
      const request = db.transaction(STORE, 'readonly').objectStore(STORE).get(RECORD_ID)
      request.onsuccess = () => { resolve(request.result as { installation_id: string; public_key_jwk: JsonWebKey; private_key: CryptoKey } | undefined) }
      request.onerror = () => { reject(request.error instanceof Error ? request.error : new Error('DEVICE_KEYS_UNAVAILABLE')) }
    })
  } finally {
    db.close()
  }
}

async function storeCount(): Promise<number> {
  const db = await openDb()
  try {
    return await new Promise((resolve, reject) => {
      const request = db.transaction(STORE, 'readonly').objectStore(STORE).count()
      request.onsuccess = () => { resolve(request.result) }
      request.onerror = () => { reject(request.error instanceof Error ? request.error : new Error('DEVICE_KEYS_UNAVAILABLE')) }
    })
  } finally {
    db.close()
  }
}

async function putCredentials(record: unknown): Promise<void> {
  const db = await openDb()
  try {
    await new Promise<void>((resolve, reject) => {
      const request = db.transaction(STORE, 'readwrite').objectStore(STORE).put(record)
      request.onsuccess = () => { resolve() }
      request.onerror = () => { reject(request.error instanceof Error ? request.error : new Error('DEVICE_KEYS_UNAVAILABLE')) }
    })
  } finally {
    db.close()
  }
}

async function verifySignature(publicKeyJwk: JsonWebKey, message: string, signature: string): Promise<boolean> {
  const publicKey = await crypto.subtle.importKey('jwk', publicKeyJwk, { name: 'ECDSA', namedCurve: 'P-256' }, true, ['verify'])
  const base64 = signature.replace(/-/g, '+').replace(/_/g, '/')
  const raw = Uint8Array.from(atob(base64 + '='.repeat((4 - (base64.length % 4)) % 4)), (char) => char.charCodeAt(0))
  return crypto.subtle.verify({ name: 'ECDSA', hash: 'SHA-256' }, publicKey, raw, new TextEncoder().encode(message))
}

describe('device-keys', () => {
  afterEach(async () => {
    await new Promise<void>((resolve) => {
      const request = indexedDB.deleteDatabase(DB_NAME)
      request.onsuccess = () => { resolve() }
      request.onerror = () => { resolve() }
      request.onblocked = () => { resolve() }
    })
  })

  it('stores a private key that is never extractable and has only the sign usage', async () => {
    await getAccessDevice()
    const stored = await storedCredentials()
    expect(stored).toBeDefined()
    expect(stored?.private_key.extractable).toBe(false)
    expect(stored?.private_key.usages).toEqual(['sign'])
    expect(stored?.private_key.type).toBe('private')
  })

  it('fails to export the stored private key', async () => {
    await getAccessDevice()
    const stored = await storedCredentials()
    if (!stored) throw new Error('credentials were not stored')
    await expect(crypto.subtle.exportKey('jwk', stored.private_key)).rejects.toThrow()
    await expect(crypto.subtle.exportKey('pkcs8', stored.private_key)).rejects.toThrow()
  })

  it('exports the public key as JWK', async () => {
    await getAccessDevice()
    const stored = await storedCredentials()
    if (!stored) throw new Error('credentials were not stored')
    expect(stored.public_key_jwk.kty).toBe('EC')
    expect(stored.public_key_jwk.crv).toBe('P-256')
    expect(typeof stored.public_key_jwk.x).toBe('string')
    expect(typeof stored.public_key_jwk.y).toBe('string')
  })

  it('reuses the same installation_id across calls', async () => {
    const first = await getAccessDevice()
    const second = await getAccessDevice()
    expect(second.installation_id).toBe(first.installation_id)
  })

  it('signs with the same key when credentials are reused', async () => {
    const first = await getAccessDevice()
    const second = await getAccessDevice()
    const signature = await second.sign('lms-recovery:challenge')
    expect(await verifySignature(first.public_key_jwk, 'lms-recovery:challenge', signature)).toBe(true)
  })

  it('reuses credentials from IndexedDB instead of regenerating them', async () => {
    await getAccessDevice()
    await getAccessDevice()
    expect(await storeCount()).toBe(1)
  })

  it('regenerates credentials when the stored private key is extractable', async () => {
    const algorithm: EcKeyGenParams = { name: 'ECDSA', namedCurve: 'P-256' }
    const pair = await crypto.subtle.generateKey(algorithm, true, ['sign', 'verify'])
    await putCredentials({
      id: RECORD_ID,
      installation_id: 'legacy-installation',
      public_key_jwk: await crypto.subtle.exportKey('jwk', pair.publicKey),
      private_key: pair.privateKey,
    })
    const device = await getAccessDevice()
    expect(device.installation_id).not.toBe('legacy-installation')
    const stored = await storedCredentials()
    expect(stored?.private_key.extractable).toBe(false)
    expect(await storeCount()).toBe(1)
  })
})