const configuredKey = import.meta.env.VITE_OFFLINE_LICENSE_PUBLIC_JWK

if (!configuredKey) throw new Error('VITE_OFFLINE_LICENSE_PUBLIC_JWK is required')

export const OFFLINE_LICENSE_PUBLIC_JWK = JSON.parse(configuredKey) as JsonWebKey
