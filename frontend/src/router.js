import { createRouter, createWebHistory } from 'vue-router'
import { englishNavigation } from './english/navigation.js'

const RouteMarker = { template: '<span />' }
const englishRoutes = Object.keys(englishNavigation.pathViews).map(path => ({ path, component: RouteMarker }))

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/english' },
    { path: '/stats', redirect: '/english/stats' },
    ...englishRoutes,
    { path: '/:pathMatch(.*)*', redirect: '/english' }
  ]
})
