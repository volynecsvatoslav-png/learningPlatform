import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const allowedHosts = (process.env.VITE_ALLOWED_HOSTS ?? 'localhost,127.0.0.1')
  .split(',')
  .map((host) => host.trim())
  .filter(Boolean)
const offlineLicensePublicJwk = process.env.VITE_OFFLINE_LICENSE_PUBLIC_JWK
  || '{"kty":"EC","x":"l242GNMQAQSa-GSVtUflOeS6m1kzEOi9oRA88cUx5v8","y":"Rw_iSGOS8Djf5dm5zVJoBwIskMOikApH8pPOp6vh0eo","crv":"P-256"}'
const apiProxyTarget = process.env.VITE_API_PROXY_TARGET ?? 'http://api:8000'
const mediaSources = (process.env.VITE_CSP_MEDIA_SOURCES ?? 'http://localhost:9000')
  .split(',')
  .map((source) => source.trim())
  .filter(Boolean)
  .join(' ')

function contentSecurityPolicy(dev: boolean): string {
  const scriptSrc = dev ? "script-src 'self' 'unsafe-inline' 'unsafe-eval' 'wasm-unsafe-eval'" : "script-src 'self' 'wasm-unsafe-eval'"
  const styleSrc = dev ? "style-src 'self' 'unsafe-inline'" : "style-src 'self'"
  const connectSrc = dev
    ? `connect-src 'self' ws://localhost:5173 ws://127.0.0.1:5173${mediaSources ? ` ${mediaSources}` : ''}`
    : `connect-src 'self'${mediaSources ? ` ${mediaSources}` : ''}`
  return [
    "default-src 'self'",
    scriptSrc,
    styleSrc,
    `img-src 'self' data: blob:${mediaSources ? ` ${mediaSources}` : ''}`,
    `media-src 'self' blob:${mediaSources ? ` ${mediaSources}` : ''}`,
    connectSrc,
    "font-src 'self' data:",
    "object-src 'none'",
    "base-uri 'none'",
    "frame-ancestors 'none'",
    "worker-src 'self'",
    "manifest-src 'self'",
  ].join('; ')
}

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
    headers: {
      'Content-Security-Policy': contentSecurityPolicy(true),
      'Referrer-Policy': 'strict-origin-when-cross-origin',
      'X-Content-Type-Options': 'nosniff',
    },
    watch: {
      usePolling: true,
    },
    proxy: {
      '/api': { target: apiProxyTarget, changeOrigin: true, xfwd: true },
      '/backoffice': { target: apiProxyTarget, changeOrigin: true, xfwd: true },
      '/static': { target: apiProxyTarget, changeOrigin: true, xfwd: true },
      '/health': { target: apiProxyTarget, changeOrigin: true, xfwd: true },
    },
  },
  preview: {
    host: '0.0.0.0',
    port: 4173,
    strictPort: true,
    headers: {
      'Content-Security-Policy': contentSecurityPolicy(false),
      'Referrer-Policy': 'strict-origin-when-cross-origin',
      'X-Content-Type-Options': 'nosniff',
    },
    proxy: {
      '/api': { target: apiProxyTarget, changeOrigin: true, xfwd: true },
      '/backoffice': { target: apiProxyTarget, changeOrigin: true, xfwd: true },
      '/static': { target: apiProxyTarget, changeOrigin: true, xfwd: true },
      '/health': { target: apiProxyTarget, changeOrigin: true, xfwd: true },
    },
  },
})