const DB_NAME = 'lms-device'
const DB_VERSION = 1
const STORE = 'credentials'
const RECORD_ID = 'main'
const encoder = new TextEncoder()

export type AccessDevice = {
  installation_id: string
  public_key_jwk: JsonWebKey
  sign: (message: string) => Promise<string>
}

type StoredCredentials = {
  id: string
  installation_id: string
  public_key_jwk: JsonWebKey
  private_key: CryptoKey
}

function base64Url(bytes: ArrayBuffer): string {
  const binary = String.fromCharCode(...new Uint8Array(bytes))
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '')
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION)
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(STORE)) request.result.createObjectStore(STORE, { keyPath: 'id' })
    }
    request.onsuccess = () => { resolve(request.result) }
    request.onerror = () => { reject(request.error ?? new Error('DEVICE_KEYS_UNAVAILABLE')) }
  })
}

async function loadCredentials(): Promise<StoredCredentials | null> {
  const db = await openDb()
  try {
    const stored = await new Promise<StoredCredentials | undefined>((resolve, reject) => {
      const request = db.transaction(STORE, 'readonly').objectStore(STORE).get(RECORD_ID)
      request.onsuccess = () => { resolve(request.result as StoredCredentials | undefined) }
      request.onerror = () => { reject(request.error instanceof Error ? request.error : new Error('DEVICE_KEYS_UNAVAILABLE')) }
    })
    if (
      stored
      && stored.private_key instanceof CryptoKey
      && !stored.private_key.extractable
    ) {
      return stored
    }
    return null
  } finally {
    db.close()
  }
}

async function saveCredentials(credentials: StoredCredentials): Promise<void> {
  const db = await openDb()
  try {
    await new Promise<void>((resolve, reject) => {
      const request = db.transaction(STORE, 'readwrite').objectStore(STORE).put(credentials)
      request.onsuccess = () => { resolve() }
      request.onerror = () => { reject(request.error instanceof Error ? request.error : new Error('DEVICE_KEYS_UNAVAILABLE')) }
    })
  } finally {
    db.close()
  }
}

async function generateCredentials(): Promise<StoredCredentials> {
  const algorithm: EcKeyGenParams = { name: 'ECDSA', namedCurve: 'P-256' }
  const pair = await crypto.subtle.generateKey(algorithm, false, ['sign', 'verify'])
  const publicKeyJwk = await crypto.subtle.exportKey('jwk', pair.publicKey)
  const stored: StoredCredentials = {
    id: RECORD_ID,
    installation_id: crypto.randomUUID(),
    public_key_jwk: publicKeyJwk,
    private_key: pair.privateKey,
  }
  await saveCredentials(stored)
  return stored
}

export async function getAccessDevice(): Promise<AccessDevice> {
  const credentials = (await loadCredentials()) ?? (await generateCredentials())
  return {
    installation_id: credentials.installation_id,
    public_key_jwk: credentials.public_key_jwk,
    sign: async (message: string) => {
      const signature = await crypto.subtle.sign({ name: 'ECDSA', hash: 'SHA-256' }, credentials.private_key, encoder.encode(message))
      return base64Url(signature)
    },
  }
}

export async function sha256Hex(value: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', encoder.encode(value))
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')
}