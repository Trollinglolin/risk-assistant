import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Dev: the dashboard calls /api/* and Vite forwards it to the FastAPI server on :8000.
// The agent endpoint needs X-API-Key; in dev the proxy adds it from the repo's .env so the
// key never ships in browser code. In production set VITE_API_BASE and enter the key in the UI.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '..', '')
  const apiKey = env.HKRISK_API_KEY
  return {
    // GitHub Pages serves a project site from /<repo>/, so the static build sets VITE_BASE
    base: process.env.VITE_BASE ?? '/',
    plugins: [react(), tailwindcss()],
    server: {
      proxy: {
        '/api': {
          target: env.HKRISK_API_URL || 'http://127.0.0.1:8000',
          changeOrigin: true,
          rewrite: (p) => p.replace(/^\/api/, ''),
          configure: (proxy) => {
            proxy.on('proxyReq', (req) => {
              if (apiKey && !req.getHeader('x-api-key')) req.setHeader('X-API-Key', apiKey)
            })
          },
        },
      },
    },
  }
})
