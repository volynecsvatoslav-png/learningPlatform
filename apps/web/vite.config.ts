import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const allowedHosts = (process.env.VITE_ALLOWED_HOSTS ?? 'localhost,127.0.0.1')
  .split(',')
  .map((host) => host.trim())
  .filter(Boolean)

export default defineConfig({
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
      '/api': { target: 'http://api:8000', changeOrigin: true },
      '/backoffice': 'http://api:8000',
      '/static': 'http://api:8000',
      '/health': 'http://api:8000',
    },
  },
  preview: {
    host: '0.0.0.0',
    port: 4173,
    strictPort: true,
  },
})
