import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// The browser talks to the Twin through /twin, so there is no CORS to set up and the operator key
// never reaches the browser. In Docker, nginx does the same (nginx/default.conf.template).
// 127.0.0.1, not localhost: uvicorn listens on IPv4 only, and localhost can resolve to ::1 first.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  const twin = env.TWIN_URL || 'http://127.0.0.1:8000'
  const operatorKey = env.TWIN_OPERATOR_KEY
  return {
    plugins: [react()],
    server: {
      proxy: {
        '/twin': {
          target: twin,
          changeOrigin: true,
          rewrite: (p: string) => p.replace(/^\/twin/, ''),
          headers: operatorKey ? { 'X-Operator-Key': operatorKey } : {},
        },
      },
    },
  }
})
