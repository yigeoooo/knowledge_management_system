import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { ElMessage } from 'element-plus'
import { restore, session } from './lib/session'

const components: Record<string, NonNullable<RouteRecordRaw['component']>> = {
  Dashboard: () => import('./views/DashboardView.vue'),
  KnowledgeQA: () => import('./views/QueryView.vue'),
  Profile: () => import('./views/ProfileView.vue'),
  KnowledgeBaseManagement: () => import('./views/ManagementView.vue'),
  DocumentManagement: () => import('./views/ManagementView.vue'),
  RobotManagement: () => import('./views/ManagementView.vue'),
  UserManagement: () => import('./views/UsersView.vue'),
  RoleManagement: () => import('./views/RoleManagementView.vue'),
  PageManagement: () => import('./views/ManagementView.vue'),
  RolePermissions: () => import('./views/PermissionsView.vue'),
  QALogs: () => import('./views/ManagementView.vue'),
  AuditLogs: () => import('./views/ManagementView.vue'),
}
export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: () => import('./views/HomeView.vue'), meta: { public: true, title: '首页' } },
    { path: '/login', name: 'login', component: () => import('./views/LoginView.vue'), meta: { public: true, title: '登录' } },
    { path: '/403', name: 'forbidden', component: () => import('./views/StatusView.vue'), meta: { public: true, title: '无访问权限' } },
    { path: '/workspace', name: 'workspace', component: () => import('./components/WorkspaceLayout.vue'), children: [] },
    { path: '/:pathMatch(.*)*', name: 'not-found', component: () => import('./views/StatusView.vue'), meta: { title: '页面未找到' } },
  ],
  scrollBehavior(to) {
    if (to.hash) return { el: to.hash, top: 92, behavior: 'smooth' }
    return { top: 0 }
  },
})
const removers: (() => void)[] = []
let registeredSignature = ''
export function installPages() {
  const signature = JSON.stringify(session.pages)
  if (signature === registeredSignature) return false
  removers.splice(0).forEach(remove => remove())
  registeredSignature = signature
  for (const page of session.pages) {
    if (!components[page.component_key] || !/^\/[a-z][a-z0-9/-]*$/.test(page.route_path) ||
      ['/', '/login', '/403', '/workspace'].includes(page.route_path) || page.page_type === 'button') continue
    removers.push(router.addRoute('workspace', {
      path: page.route_path, name: `page:${page.code}`, component: components[page.component_key],
      meta: { title: page.name, pageCode: page.code },
    }))
  }
  return true
}
export function entryPath() {
  return session.pages.find(p => router.hasRoute(`page:${p.code}`))?.route_path || '/403'
}
export function loginDestination(value: unknown) {
  if (typeof value === 'string' && value.startsWith('/') && !value.startsWith('//')) {
    const target = router.resolve(value)
    if (session.pages.some(p => p.route_path === target.path && router.hasRoute(`page:${p.code}`))) return value
  }
  return entryPath()
}
router.beforeEach(async to => {
  if (to.name === 'home') return true
  try { await restore() } catch (error) { ElMessage.error((error as Error).message) }
  const changed = installPages()
  if (to.name === 'login') return session.user ? loginDestination(to.query.redirect) : true
  if (to.meta.public) return true
  if (!session.user) return { name: 'login', query: { redirect: to.fullPath } }
  if (to.path === '/workspace') return entryPath()
  if (changed) return { path: to.fullPath, replace: true }
  if (to.name === 'not-found') return '/403'
  if (!session.pages.some(p => p.route_path === to.path)) return '/403'
  return true
})
router.afterEach(to => { document.title = `${to.meta.title || '知识平台'} · 跨维智能` })
window.addEventListener('session-expired', () => {
  installPages()
  if (!router.currentRoute.value.meta.public) {
    void router.replace({ name: 'login', query: { redirect: router.currentRoute.value.fullPath } })
  }
})
