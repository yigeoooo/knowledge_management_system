import { createRouter, createWebHashHistory } from 'vue-router'
import { ElMessage } from 'element-plus'
import { restore, session } from '@web/lib/session'
import { pages, type PageKey } from './pages'
import Login from './Login.vue'

export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/login', name: 'login', component: Login },
    { path: '/403', name: 'denied', component: () => import('./Denied.vue') },
    { path: '/:pathMatch(.*)*', name: 'unknown', component: () => import('./Denied.vue') },
  ],
})
export const firstPage = () => session.pages.find(p => p.component_key === 'Dashboard')?.route_path ||
  session.pages.find(p => p.is_visible)?.route_path || session.pages[0]?.route_path || '/403'
let lastPages = ''
let removePages: (() => void)[] = []
export function syncPages() {
  const signature = JSON.stringify(session.pages)
  if (lastPages === signature) return false
  removePages.forEach(remove => remove())
  removePages = session.pages.map(p => router.addRoute({
    name: p.code, path: p.route_path, component: pages[p.component_key as PageKey].view,
    props: p.component_key === 'QALogs' ? { allowExport: false, stepped: true } : undefined,
    meta: { title: p.name, key: p.component_key },
  }))
  lastPages = signature
  return true
}
router.beforeEach(async to => {
  if (!session.ready) {
    try { await restore() } catch (e) { ElMessage.error((e as Error).message) }
  }
  const changed = syncPages()
  if (!session.user) return to.name === 'login' || { path: '/login', query: to.path === '/' ? {} : { redirect: to.fullPath } }
  if (to.path === '/' || to.name === 'login' || to.path === '/workspace') return firstPage()
  if (to.path === '/403') return true
  if (!session.pages.some(p => p.route_path === to.path)) return '/403'
  if (changed) return to.fullPath
  return true
})
window.addEventListener('session-expired', () => { void router.replace('/login') })
