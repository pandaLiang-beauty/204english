import { createRouter, createWebHistory } from 'vue-router'
import { englishNavigation } from './english/navigation.js'

const RouteMarker = { template: '<span />' }
const englishRoutes = Object.keys(englishNavigation.pathViews).map(path => ({ path, component: RouteMarker }))

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    ...englishRoutes,
    // 旧地址兼容：路径前缀从 /english 拉平到 / 之前存下的书签仍然可用。
    { path: '/english', redirect: '/' },
    { path: '/english/:rest(.*)', redirect: to => `/${to.params.rest}` },
    { path: '/:pathMatch(.*)*', redirect: '/' }
  ]
})
