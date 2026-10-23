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
export const apiBase = base

export class ApiError extends Error {
  constructor(message: string, public status: number, public code = 0) { super(message) }
}
interface ApiRequestOptions extends RequestInit { timeoutMs?: number }
async function request<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  const { timeoutMs = 15000, signal, ...init } = options
  const timeout = AbortSignal.timeout(timeoutMs)
  let response: Response
  try {
    response = await fetch(`${base}${path}`, {
      ...init, credentials: 'include', signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
      headers: { 'Content-Type': 'application/json', ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}), ...options.headers },
    })
  } catch {
    if (signal?.aborted) throw new DOMException('请求已取消', 'AbortError')
    throw new ApiError(timeout.aborted ? '请求超时，请点击重试获取结果' : '连接服务失败，请检查网络后重试', 0)
  }
  const body = await response.json().catch(() => {
    if (signal?.aborted) throw new DOMException('请求已取消', 'AbortError')
    if (timeout.aborted) throw new ApiError('请求超时，请点击重试获取结果', 0)
    return null
  })
  if (!response.ok || !body || body.code !== 0) {
    throw new ApiError(body?.message || '服务暂不可用，请稍后再试', response.status, body?.code)
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
export async function api<T>(path: string, options?: ApiRequestOptions): Promise<T> {
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

export async function uploadFile<T>(path: string, file: Blob, contentType?: string): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${base}${path}`, {
      method: 'PUT',
      credentials: 'include',
      body: file,
      signal: AbortSignal.timeout(120000),
      headers: {
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        'Content-Type': contentType || file.type || 'application/octet-stream',
      },
    })
  } catch {
    throw new ApiError('上传文件失败，请检查网络后重试', 0)
  }
  const body = await response.json().catch(() => null)
  if (!response.ok || !body || body.code !== 0) {
    throw new ApiError(body?.message || '文件上传失败，请稍后再试', response.status)
  }
  return body.data as T
}
export async function logout() {
  await api('/auth/logout', { method: 'POST', body: '{}' })
  clearSession()
}
