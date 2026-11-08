import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// One bundle, served by both mocks; it asks /api/identity which console to show. In development
// point MOCK_URL at the mock to work on (default: the City Brain).
export default defineConfig(({ mode }) => {
  const target = loadEnv(mode, '.', '').MOCK_URL || 'http://127.0.0.1:8002'
  return {
    plugins: [react()],
    server: { proxy: { '/api': target, '/events': target } },
  }
})
