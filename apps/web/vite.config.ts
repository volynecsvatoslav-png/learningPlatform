import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const allowedHosts = (process.env.VITE_ALLOWED_HOSTS ?? 'localhost,127.0.0.1')
  .split(',')
  .map((host) => host.trim())
  .filter(Boolean)
const offlineLicensePublicJwk = process.env.VITE_OFFLINE_LICENSE_PUBLIC_JWK
  ?? '{"kty":"EC","x":"l242GNMQAQSa-GSVtUflOeS6m1kzEOi9oRA88cUx5v8","y":"Rw_iSGOS8Djf5dm5zVJoBwIskMOikApH8pPOp6vh0eo","crv":"P-256"}'
const apiProxyTarget = process.env.VITE_API_PROXY_TARGET ?? 'http://api:8000'

export default defineConfig({
  define: {
    'import.meta.env.VITE_OFFLINE_LICENSE_PUBLIC_JWK': JSON.stringify(offlineLicensePublicJwk),
  },
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    allowedHosts,
    watch: {
      usePolling: true,
    },
    proxy: {
      '/api': { target: apiProxyTarget, changeOrigin: true },
      '/backoffice': apiProxyTarget,
      '/static': apiProxyTarget,
      '/health': apiProxyTarget,
    },
  },
  preview: {
    host: '0.0.0.0',
    port: 4173,
    strictPort: true,
    proxy: {
      '/api': { target: apiProxyTarget, changeOrigin: true },
      '/backoffice': apiProxyTarget,
      '/static': apiProxyTarget,
      '/health': apiProxyTarget,
    },
  },
})
