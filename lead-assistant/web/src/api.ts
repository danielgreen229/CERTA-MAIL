// Клиент API: все действия интерфейса идут через эти функции.

export type Role = 'manager' | 'supervisor' | 'admin'

export interface User {
  id: number
  login: string
  name: string
  role: Role
  must_change_password: boolean
}

export interface Reason {
  code: string
  text: string
}

export interface LeadSummary {
  id: number | string
  key: string
  date: string | null
  channel: string | null
  source: string
  name: string | null
  contact: string | null
  subject: string | null
  text: string | null
  status: string
  category: string | null
  priority: string | null
  state: 'new' | 'pending' | 'accepted' | 'corrected' | 'rejected'
  state_title: string
  needs_review: boolean
  review_reasons: Reason[]
  assignee: string | null
  due_at: string | null
  overdue: boolean
  result_version: number | null
}

export interface Found {
  value: unknown
  quote: string
}

export interface ResultVersion {
  id: number
  version: number
  category: string | null
  priority: string | null
  draft_reply: string | null
  analysis: Record<string, unknown>
  run_id: string | null
  source: string
  created_at: string
}

export interface DecisionInfo {
  id: number
  action: 'accept' | 'correct' | 'reject'
  category: string | null
  priority: string | null
  draft_reply: string | null
  reason: string | null
  changes: Record<string, { from: unknown; to: unknown }>
  user: string
  created_at: string
}

export interface KbHit {
  chunk_id: number
  page: number | null
  fragment: string
  source: string
  document: { id: number; title: string; version: string; owner: string }
}

export interface LeadDetail extends LeadSummary {
  lead: Record<string, unknown>
  result: ResultVersion | null
  decision: DecisionInfo | null
  extraction: {
    fields: Record<string, Found[] | null>
    contradictions: string[]
    missing: string[]
  }
  field_titles: Record<string, string>
  history: Array<Record<string, unknown> & { type: string; at: string }>
  knowledge: { results: KbHit[]; conflicts: string[] }
  shipments: Array<{ number: string; data?: Record<string, unknown>; error?: string; source: string; fetched_at: string }>
  reply: { available: boolean; reason: string | null; channel: 'email' | 'telegram'; to: string | null; from: string | null; subject: string | null }
  replies: SentReply[]
}

export interface SentReply {
  id: number
  to: string
  subject: string | null
  body: string
  status: 'sent' | 'failed'
  error: string | null
  user: string
  at: string
}

export interface Job {
  id: string
  state: 'queued' | 'running' | 'done' | 'failed' | 'cancelled'
  created_at: string
  started_at: string | null
  finished_at: string | null
  heartbeat_at: string | null
  attempts: number
  max_attempts: number
  progress: { total?: number; done?: number; pending_ids?: unknown[]; log?: string[]; error?: string }
  run_ids: string[]
  summary: {
    text?: string
    counts?: Record<string, number>
    urgent?: Array<{ id: unknown; basis: string | null; next: string | null }>
    failed?: unknown[]
    model?: string
  } | null
  error: { code: string; message?: string } | null
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message)
  }
}

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { 'X-Requested-With': 'lead-assistant' }
  let payload: BodyInit | undefined
  if (body instanceof FormData) {
    payload = body
  } else if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }
  let response: Response
  try {
    response = await fetch(url, { method, headers, body: payload, credentials: 'same-origin' })
  } catch {
    throw new ApiError(0, 'NETWORK', 'Сервер недоступен. Проверьте соединение.')
  }
  const text = await response.text()
  let data: unknown = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = null
  }
  if (!response.ok) {
    const error = (data as { error?: { code?: string; message?: string } } | null)?.error
    throw new ApiError(response.status, error?.code ?? 'HTTP', error?.message ?? `Ошибка ${response.status}`)
  }
  return data as T
}

export const api = {
  get: <T>(url: string) => request<T>('GET', url),
  post: <T>(url: string, body?: unknown) => request<T>('POST', url, body ?? {}),
  put: <T>(url: string, body?: unknown) => request<T>('PUT', url, body ?? {}),
  del: <T>(url: string) => request<T>('DELETE', url),
}

export const leadUrl = (key: string) => `/api/leads/${encodeURIComponent(key)}`

export const CATEGORY: Record<string, string> = {
  sale: 'Продажа',
  complaint: 'Жалоба',
  question: 'Вопрос',
  spam: 'Спам',
}
export const PRIORITY: Record<string, string> = { high: 'Высокий', medium: 'Средний', low: 'Низкий' }
export const ROLE: Record<Role, string> = {
  manager: 'Менеджер',
  supervisor: 'Руководитель',
  admin: 'Администратор',
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const hasTime = value.includes('T')
  return date.toLocaleString('ru-RU', hasTime
    ? { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' }
    : { day: '2-digit', month: '2-digit', year: 'numeric' })
}
