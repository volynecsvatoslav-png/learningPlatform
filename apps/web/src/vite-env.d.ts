/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_ENABLE_SERVICE_WORKER?: string
  readonly VITE_OFFLINE_LICENSE_PUBLIC_JWK: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
