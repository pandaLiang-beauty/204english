import { defineConfig } from 'vite'
import { fileURLToPath } from 'node:url'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

const backendTarget = process.env.STUDY_LOCAL_BACKEND || 'http://127.0.0.1:8204'
const iconBarrel = fileURLToPath(new URL('./src/icons.js', import.meta.url))

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
  resolve: {
    // 组件里写的 `from '@lucide/vue'` 全部转到 src/icons.js（只含实际用到的 25 个图标）。
    // 整库 barrel 在 dev 下会被预打包成 4.2MB / 过隧道 558KB，是首屏最大的一块。
    // 用正则精确匹配，否则 icons.js 里的 '@lucide/vue/dist/esm/icons/...' 也会被一起改写。
    alias: [{ find: /^@lucide\/vue$/, replacement: iconBarrel }]
  },
  // 显式声明 icons.js 用到的那个深路径。不声明的话它可能在页面加载时才被「发现」，
  // vite 会中途重跑一次预打包并强制刷新页面；重跑出来的 chunk 和已经加载的那批
  // ?v= 版本戳不一致时，vue 和 vue-router 会变成两份，injection Symbol 对不上，
  // 页面直接白屏（报 injection "Symbol(router)" not found）。
  optimizeDeps: {
    include: ['@lucide/vue/dist/esm/createLucideIcon.mjs']
  },
  server: {
    host: process.env.STUDY_FRONTEND_HOST || '127.0.0.1',
    port: Number(process.env.STUDY_FRONTEND_PORT || 5204),
    // Cloudflare 隧道把 Host 原样带过来，不在白名单里 vite 直接 403。
    ...(publicHost ? { allowedHosts: [publicHost] } : {}),
    // HMR 的 socket 要按浏览器看到的地址连：页面是 https/443，
    // 默认值会让客户端去连隧道外不存在的 5204。
    ...(publicHost ? { hmr: { protocol: 'wss', host: publicHost, clientPort: 443 } } : {}),
    proxy: {
      '/api': backendTarget
    }
  }
})
