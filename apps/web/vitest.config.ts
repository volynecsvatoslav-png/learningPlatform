import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  define: {
    'import.meta.env.VITE_OFFLINE_LICENSE_PUBLIC_JWK': JSON.stringify('{"kty":"EC","x":"l242GNMQAQSa-GSVtUflOeS6m1kzEOi9oRA88cUx5v8","y":"Rw_iSGOS8Djf5dm5zVJoBwIskMOikApH8pPOp6vh0eo","crv":"P-256"}'),
  },
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test-setup.ts',
  },
})
