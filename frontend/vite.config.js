import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

const backendTarget = process.env.STUDY_LOCAL_BACKEND || 'http://127.0.0.1:8103'
const publicBasePath = '/english'

export default defineConfig({
  base: `${publicBasePath}/`,
  plugins: [vue(), tailwindcss()],
  server: {
    host: '127.0.0.1',
    port: 5103,
    proxy: {
      [`${publicBasePath}/api`]: {
        target: backendTarget,
        rewrite: path => path.slice(publicBasePath.length)
      },
      '/api': backendTarget
    }
  }
})
