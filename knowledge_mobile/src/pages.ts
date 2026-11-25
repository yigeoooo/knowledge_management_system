import { computed } from 'vue'
import { session, type Page } from '@web/lib/session'

export const pages = {
  Dashboard: { view: () => import('./Workbench.vue') },
  KnowledgeQA: { view: () => import('./Chat.vue') },
  RobotQA: { view: () => import('./RobotChat.vue') },
  Profile: { view: () => import('./Profile.vue') },
  RobotManagement: { view: () => import('./records/Robots.vue') },
  UserManagement: { view: () => import('./records/Users.vue') },
  RoleManagement: { view: () => import('./records/Roles.vue') },
  PageManagement: { view: () => import('./records/Resources.vue') },
  RolePermissions: { view: () => import('./Permissions.vue') },
  QALogs: { view: () => import('./History.vue') },
  AuditLogs: { view: () => import('./records/Resources.vue') },
}
export type PageKey = keyof typeof pages
export function supported(p: Page) {
  return Object.hasOwn(pages, p.component_key) && p.page_type !== 'button' &&
    /^\/[a-z][a-z0-9/-]*$/.test(p.route_path) && !['/login', '/workspace', '/403'].includes(p.route_path)
}
export const visible = computed(() => session.pages.filter(p => p.is_visible).sort((a,b) => a.sort_order - b.sort_order))
const icons: Record<PageKey, string> = { Dashboard:'wap-home-o', KnowledgeQA:'chat-o', RobotQA:'service-o', Profile:'user-o', RobotManagement:'desktop-o', UserManagement:'friends-o', RoleManagement:'manager-o', PageManagement:'apps-o', RolePermissions:'shield-o', QALogs:'records-o', AuditLogs:'notes-o' }
export const mobileIcon = (p: Page) => icons[p.component_key as PageKey]
