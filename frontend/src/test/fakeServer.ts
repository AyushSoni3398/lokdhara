/** A tiny stand-in for the API in component tests: routes are "METHOD /path" → handler. */
import { vi } from 'vitest'

export interface FakeRequest {
  method: string
  path: string
  headers: Headers
  body: unknown
}

type Reply = { status?: number; body?: unknown; headers?: Record<string, string> }
type Handler = (request: FakeRequest) => Reply | Promise<Reply>

export function problem(status: number, code: string): Reply {
  return {
    status,
    body: { status, code, title: code, type: `https://lokdhara.example/errors/${code}` },
  }
}

export function fakeServer(routes: Record<string, Handler>) {
  const requests: FakeRequest[] = []
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://localhost')
    const method = init?.method ?? 'GET'
    const path = url.pathname.replace(/^\/api\/v1/, '') + url.search
    const body =
      typeof init?.body === 'string' ? JSON.parse(init.body) : ((init?.body as unknown) ?? null)
    const request = { method, path, headers: new Headers(init?.headers), body }
    requests.push(request)
    const key = Object.keys(routes).find((route) => {
      const [routeMethod, pattern] = route.split(' ')
      return routeMethod === method && new RegExp(`^${pattern}$`).test(path)
    })
    const reply = key ? await routes[key]!(request) : problem(404, 'not_found')
    const status = reply.status ?? 200
    return new Response(status === 204 ? null : JSON.stringify(reply.body ?? {}), {
      status,
      headers: { 'Content-Type': 'application/json', ...reply.headers },
    })
  })
  vi.stubGlobal('fetch', fetchMock)
  return { requests }
}

export const SESSION = {
  user: { id: 'u1', username: 'asha', display_name: 'Asha', preferred_locale: 'hi' },
  roles: [{ role: 'contributor', scope: null }],
  csrf_token: 'csrf-1',
  mfa_enabled: false,
  mfa_setup_required: false,
}

export const SPEAKER = {
  id: 's1',
  speaker_code: 'SPK-7Q3M9A',
  is_self: true,
  status: 'active',
  has_active_consent: true,
  dialect_label: null,
}
