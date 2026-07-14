import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // Proxy the API in development so the browser sees a single origin and the
      // session cookie is same-site. In production the two are separate Render
      // services and the cookie is SameSite=None; Secure — see server/app/config.py.
      '/api': {
        target: 'http://localhost:5555',
        changeOrigin: true,
      },
    },
  },
})
