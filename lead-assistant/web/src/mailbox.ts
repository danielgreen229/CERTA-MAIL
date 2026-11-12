import { reactive } from 'vue'
import { api, ApiError, type Job, type LeadSummary } from './api'
import { chime, systemNotice } from './notify'

/** Общее состояние «Почты»: список, фильтры, папки. Его видят и страница, и боковое меню. */
export interface SourceTab {
  key: string
  title: string
  mailbox: boolean
  count: number
  open: number
}

export interface ListResponse {
  leads: LeadSummary[]
  counts: Record<string, number>
  folders: Record<string, number>
  sources: SourceTab[]
  active_job: Job | null
}

export type FilterKey = 'q' | 'category' | 'priority' | 'state' | 'review' | 'source' | 'overdue'
export type FolderFilter = Partial<Record<Exclude<FilterKey, 'q'>, string>>

export const EMPTY_FILTERS: Record<FilterKey, string> = {
  q: '', category: '', priority: '', state: '', review: '', source: '', overdue: '',
}

export const filters = reactive<Record<FilterKey, string>>({ ...EMPTY_FILTERS })

export const mail = reactive({
  data: null as ListResponse | null,
  loading: true,
  error: '',
  /** Короткое сообщение о новых письмах (всплывает внизу справа). */
  toast: '',
})

let knownTotal: number | null = null
let toastTimer: number | undefined

function plural(n: number): string {
  const tail = n % 10
  const tens = n % 100
  if (tail === 1 && tens !== 11) return 'новое письмо'
  if (tail >= 2 && tail <= 4 && (tens < 12 || tens > 14)) return 'новых письма'
  return 'новых писем'
}

function announce(total: number) {
  if (knownTotal !== null && total > knownTotal) {
    const fresh = total - knownTotal
    mail.toast = `Пришло ${fresh} ${plural(fresh)}`
    window.clearTimeout(toastTimer)
    toastTimer = window.setTimeout(() => (mail.toast = ''), 8000)
    chime()
    systemNotice('Certa · Почта', mail.toast)
  }
  knownTotal = total
}

export function queryString(extra: Record<string, string> = {}): string {
  const params = new URLSearchParams(Object.entries({ ...filters, ...extra }).filter(([, v]) => v))
  return params.toString()
}

export async function loadMail(silent = false) {
  if (!silent) mail.loading = true
  try {
    const next = await api.get<ListResponse>(`/api/leads?${queryString()}`)
    announce(next.counts.total ?? 0)
    mail.data = next
    mail.error = ''
    const waiting = (next.counts.new ?? 0) + (next.counts.pending ?? 0)
    document.title = waiting ? `(${waiting}) Почта · Certa` : 'Почта · Certa'
  } catch (e) {
    mail.error = e instanceof ApiError ? e.message : 'Не удалось загрузить письма'
  } finally {
    mail.loading = false
  }
}

/** Папка задаёт набор фильтров целиком; строка поиска и вкладка категории сохраняются. */
export function applyFolder(folder: FolderFilter, keepCategory = false) {
  const category = keepCategory ? filters.category : ''
  Object.assign(filters, { ...EMPTY_FILTERS, q: filters.q, category, ...folder })
}

export function isFolderActive(folder: FolderFilter): boolean {
  const keys: Array<Exclude<FilterKey, 'q' | 'category'>> = ['priority', 'state', 'review', 'source', 'overdue']
  return keys.every((key) => (filters[key] ?? '') === (folder[key] ?? ''))
}

let poll: number | undefined
let ticks = 0

/** Опрос: каждые 4 с во время обработки, иначе раз в 16 с — так приходят новые письма. */
export function startPolling() {
  if (poll) return
  poll = window.setInterval(() => {
    ticks += 1
    if (mail.data?.active_job || ticks % 4 === 0) loadMail(true)
  }, 4000)
}

export function stopPolling() {
  window.clearInterval(poll)
  poll = undefined
  knownTotal = null
}
