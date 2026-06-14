import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import vuetify from 'vite-plugin-vuetify'

// The Semaphore instance to integrate with. Override with SEMAPHORE_URL env var.
const DEFAULT_SEMAPHORE_URL = 'https://cicd-ucaas.mycountrymobile.com'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = env.SEMAPHORE_URL || DEFAULT_SEMAPHORE_URL
  // Optional token prefill for local development convenience. The token is
  // primarily entered through the app's Connect screen at runtime.
  const token = env.SEMAPHORE_API_TOKEN || env.VITE_SEMAPHORE_TOKEN || ''

  return {
    plugins: [
      vue(),
      vuetify({ autoImport: true }),
    ],
    define: {
      'import.meta.env.VITE_SEMAPHORE_TOKEN': JSON.stringify(token),
      'import.meta.env.VITE_SEMAPHORE_URL': JSON.stringify(target),
    },
    server: {
      host: '0.0.0.0',
      port: 5173,
      // Proxy keeps API calls same-origin in the browser, avoiding CORS and
      // forwarding the Authorization: Bearer header to Semaphore.
      proxy: {
        '/api': {
          target,
          changeOrigin: true,
          secure: true,
        },
      },
    },
  }
})
