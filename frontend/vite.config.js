import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

const backendTarget = process.env.STUDY_LOCAL_BACKEND || 'http://127.0.0.1:8113'

// 隧道域名从 STUDY_PUBLIC_ORIGIN 推出来（.env.local 里已有 https://204.xpliang.tech）。
// 没设就当纯本机开发，跳过下面两项隧道适配。
function tunnelHost() {
  const origin = String(process.env.STUDY_PUBLIC_ORIGIN || '').trim()
  if (!origin) return ''
  try {
    return new URL(origin).hostname
  } catch {
    return ''
  }
}

const publicHost = tunnelHost()

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  server: {
    host: process.env.STUDY_FRONTEND_HOST || '127.0.0.1',
    port: Number(process.env.STUDY_FRONTEND_PORT || 5103),
    // Cloudflare 隧道把 Host 原样带过来，不在白名单里 vite 直接 403。
    ...(publicHost ? { allowedHosts: [publicHost] } : {}),
    // HMR 的 socket 要按浏览器看到的地址连：页面是 https/443，
    // 默认值会让客户端去连隧道外不存在的 5103。
    ...(publicHost ? { hmr: { protocol: 'wss', host: publicHost, clientPort: 443 } } : {}),
    proxy: {
      '/api': backendTarget
    }
  }
})
