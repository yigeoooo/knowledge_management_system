import { Capacitor, CapacitorHttp } from '@capacitor/core'

export const native = Capacitor.isNativePlatform()
const deviceOrigin = 'http://8.156.42.130:5000'
export async function send(path: string, init: RequestInit, timeoutMs: number) {
  const url = (native ? deviceOrigin : '') + '/api/v1' + path
  if (!native) return fetch(url, init)
  const signal = init.signal
  if (signal?.aborted) throw new DOMException('请求已取消', 'AbortError')
  return new Promise<Response>((resolve, reject) => {
    const cancel = () => reject(new DOMException('请求已取消', 'AbortError'))
    signal?.addEventListener('abort', cancel, { once: true })
    CapacitorHttp.request({
      url, method: init.method || 'GET', headers: init.headers as Record<string, string>,
      data: typeof init.body === 'string' ? JSON.parse(init.body) : undefined,
      responseType: 'json', connectTimeout: timeoutMs, readTimeout: timeoutMs,
      disableRedirects: true,
    }).then(result => new Response(JSON.stringify(result.data), { status: result.status }))
      .then(resolve, reject).finally(() => signal?.removeEventListener('abort', cancel))
  })
}
