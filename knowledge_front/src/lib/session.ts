import { reactive } from 'vue'

export interface Page {
  code: string; name: string; route_path: string; route_name: string
  component_key: string; page_type: string; sort_order: number; is_visible: boolean
}
export interface User {
  id: string; username: string; display_name: string; role: string; role_name: string
}
interface Identity { user: User; pages: Page[]; access_token: string }
export const session = reactive({ user: null as User | null, pages: [] as Page[], ready: false })
let accessToken = ''
let refreshing: Promise<void> | null = null
const base = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message) }
}
async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${base}${path}`, {
      ...options, credentials: 'include', signal: AbortSignal.timeout(15000),
      headers: { 'Content-Type': 'application/json', ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}), ...options.headers },
    })
  } catch { throw new ApiError('连接服务失败，请检查网络后重试', 0) }
  const body = await response.json().catch(() => null)
  if (!response.ok || !body || body.code !== 0) {
    throw new ApiError(body?.message || '服务暂不可用，请稍后再试', response.status)
  }
  return body.data as T
}
function accept(data: Identity) {
  accessToken = data.access_token
  session.user = data.user
  session.pages = data.pages
  session.ready = true
}
export function clearSession() {
  accessToken = ''
  session.user = null
  session.pages = []
  session.ready = true
}
export async function login(username: string, password: string) {
  accept(await request<Identity>('/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) }))
}
export function refresh() {
  if (!refreshing) {
    refreshing = request<Identity>('/auth/refresh', { method: 'POST', body: '{}' })
      .then(accept).finally(() => { refreshing = null })
  }
  return refreshing
}
export async function restore() {
  if (session.ready) return
  try { await refresh() } catch (error) {
    clearSession()
    if (error instanceof ApiError && error.status !== 401) throw error
  }
}
export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  try { return await request<T>(path, options) } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 401) throw error
    try { await refresh() } catch (refreshError) {
      if (refreshError instanceof ApiError && refreshError.status === 401) {
        clearSession()
        window.dispatchEvent(new Event('session-expired'))
      }
      throw refreshError
    }
    return request<T>(path, options)
  }
}
export async function logout() {
  await api('/auth/logout', { method: 'POST', body: '{}' })
  clearSession()
}
