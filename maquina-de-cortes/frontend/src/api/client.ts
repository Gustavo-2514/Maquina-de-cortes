export class ApiError extends Error {
  status: number
  detail: unknown
  technical?: string
  constructor(status: number, message: string, detail?: unknown, technical?: string) {
    super(message)
    this.status = status
    this.detail = detail
    this.technical = technical
  }
}

function extractMessage(body: unknown, status: number): { message: string; technical?: string } {
  if (body && typeof body === 'object' && 'detail' in body) {
    const d = (body as { detail: unknown }).detail
    if (typeof d === 'string') return { message: d }
    if (d && typeof d === 'object' && 'message' in d) {
      const o = d as { message: string; detail?: string }
      return { message: o.message, technical: o.detail }
    }
    if (Array.isArray(d)) return { message: 'Dados inválidos', technical: JSON.stringify(d) }
  }
  return { message: `Erro ${status}` }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!res.ok) {
    let body: unknown
    try {
      body = await res.json()
    } catch {
      body = undefined
    }
    const { message, technical } = extractMessage(body, res.status)
    throw new ApiError(res.status, message, body, technical)
  }
  return res.json() as Promise<T>
}

export const post = <T>(path: string, body?: unknown) =>
  api<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })
