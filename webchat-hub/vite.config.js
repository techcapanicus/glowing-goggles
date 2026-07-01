import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import vuetify from 'vite-plugin-vuetify'

const DEFAULT_TENANT = 'https://efcx4.expertflow.com'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const tenant = env.EF_TENANT_URL || DEFAULT_TENANT

  const proxyPaths = [
    '/unified-admin',
    '/ccm',
    '/bot-framework',
    '/customer-widget',
    '/web-channel-manager',
    '/cx-tenant',
  ]

  const proxy = Object.fromEntries(
    proxyPaths.map((path) => [
      path,
      { target: tenant, changeOrigin: true, secure: true },
    ]),
  )

  const base = env.VITE_BASE_PATH || '/'

  return {
    base,
    plugins: [vue(), vuetify({ autoImport: true })],
    server: {
      host: '0.0.0.0',
      port: 5174,
      proxy,
      allowedHosts: true,
    },
    preview: {
      host: '0.0.0.0',
      port: 5174,
      proxy,
      allowedHosts: true,
    },
  }
})
