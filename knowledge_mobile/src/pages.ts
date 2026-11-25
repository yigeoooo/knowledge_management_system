import { ChatDotRound, Cpu, Grid, User, Monitor, SetUp, Key, Tickets, Document, Avatar, Operation } from '@element-plus/icons-vue'
import { computed } from 'vue'
import { session, type Page } from '@web/lib/session'

export const pages = {
  Dashboard: { view: () => import('./Workbench.vue'), icon: Grid },
  KnowledgeQA: { view: () => import('@web/views/QueryView.vue'), icon: ChatDotRound },
  RobotQA: { view: () => import('@web/views/RobotQueryView.vue'), icon: Cpu },
  Profile: { view: () => import('@web/views/ProfileView.vue'), icon: User },
  RobotManagement: { view: () => import('./records/Robots.vue'), icon: Operation },
  UserManagement: { view: () => import('./records/Users.vue'), icon: Avatar },
  RoleManagement: { view: () => import('./records/Roles.vue'), icon: SetUp },
  PageManagement: { view: () => import('./records/Resources.vue'), icon: Monitor },
  RolePermissions: { view: () => import('@web/views/PermissionsView.vue'), icon: Key },
  QALogs: { view: () => import('@web/views/ConversationHistoryView.vue'), icon: Tickets },
  AuditLogs: { view: () => import('./records/Resources.vue'), icon: Document },
}
export type PageKey = keyof typeof pages
export function supported(p: Page) {
  return Object.hasOwn(pages, p.component_key) && p.page_type !== 'button' &&
    /^\/[a-z][a-z0-9/-]*$/.test(p.route_path) && !['/login', '/workspace', '/403'].includes(p.route_path)
}
export const visible = computed(() => session.pages.filter(p => p.is_visible).sort((a,b) => a.sort_order - b.sort_order))
export const iconFor = (p: Page) => pages[p.component_key as PageKey].icon
