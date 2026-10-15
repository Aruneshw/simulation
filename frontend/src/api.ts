import type { Project } from './types'

export class ApiError extends Error {
  constructor(public status: number, public body: unknown) {
    super(typeof body === 'object' && body && 'detail' in body ? String((body as { detail: unknown }).detail) : `HTTP ${status}`)
  }
}

async function req<T>(method: string, url: string, body?: unknown, params?: Record<string, unknown>): Promise<T> {
  const q = params
    ? '?' + new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '').map(([k, v]) => [k, String(v)])).toString()
    : ''
  const init: RequestInit = { method, headers: {} }
  if (body instanceof FormData) init.body = body
  else if (body !== undefined) {
    init.body = JSON.stringify(body)
    ;(init.headers as Record<string, string>)['Content-Type'] = 'application/json'
  }
  const r = await fetch(url + q, init)
  const ct = r.headers.get('content-type') ?? ''
  const data = ct.includes('json') ? await r.json() : await r.text()
  if (!r.ok) throw new ApiError(r.status, data)
  return data as T
}

export const api = {
  get: <T>(url: string, params?: Record<string, unknown>) => req<T>('GET', url, undefined, params),
  post: <T>(url: string, body?: unknown, params?: Record<string, unknown>) => req<T>('POST', url, body, params),
  put: <T>(url: string, body?: unknown) => req<T>('PUT', url, body),
  del: <T>(url: string) => req<T>('DELETE', url),
}

/** POST a project to an export endpoint and trigger a browser download. */
export async function download(fmt: string, project: Project, params?: Record<string, string>) {
  const q = params ? '?' + new URLSearchParams(params).toString() : ''
  const r = await fetch(`/api/export/${fmt}${q}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(project) })
  if (!r.ok) throw new ApiError(r.status, await r.json().catch(() => ({})))
  const blob = await r.blob()
  const cd = r.headers.get('content-disposition') ?? ''
  const name = /filename="([^"]+)"/.exec(cd)?.[1] ?? `${fmt}.bin`
  saveBlob(blob, name)
  const rep = r.headers.get('x-roboverse-export-report')
  return rep ? JSON.parse(rep) : null
}

export function saveBlob(blob: Blob, name: string) {
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = name
  a.click()
  setTimeout(() => URL.revokeObjectURL(a.href), 2000)
}

export function wsUrl(path: string) {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}${path}`
}
