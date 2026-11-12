<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, ApiError, CATEGORY, PRIORITY, type Job, type LeadSummary } from '../api'
import Icon, { type IconName } from '../components/Icon.vue'
import LeadCard from '../components/LeadCard.vue'
import UiSelect from '../components/UiSelect.vue'
import { applyFolder, EMPTY_FILTERS, filters, loadMail, mail, queryString, type FilterKey } from '../mailbox'

const route = useRoute()
const router = useRouter()
const jobError = ref('')
const selected = computed(() => (route.params.key ? String(route.params.key) : null))

// Фильтры берутся из адреса страницы (ссылку на папку можно переслать) и пишутся обратно.
for (const key of Object.keys(EMPTY_FILTERS) as FilterKey[]) {
  if (route.query[key] !== undefined) filters[key] = String(route.query[key])
}
let debounce: number | undefined
watch(filters, () => {
  window.clearTimeout(debounce)
  debounce = window.setTimeout(() => {
    const query = Object.fromEntries(Object.entries(filters).filter(([, v]) => v))
    router.replace({ path: route.path, query })
    loadMail()
  }, 200)
})

const data = computed(() => mail.data)
const counts = computed(() => data.value?.counts ?? {})
const f = (key: string) => data.value?.folders[key] ?? 0
const job = computed<Job | null>(() => data.value?.active_job ?? null)
const jobPercent = computed(() => {
  const p = job.value?.progress
  return p && p.total ? Math.round(((p.done ?? 0) / p.total) * 100) : 0
})

/** Заголовок страницы — по выбранной папке, человеческими словами. */
const title = computed(() => {
  const source = data.value?.sources.find((s) => s.key === filters.source)
  const parts: string[] = []
  if (source) parts.push(source.title)
  if (filters.priority) parts.push(`${PRIORITY[filters.priority] ?? ''} срочность`)
  const state: Record<string, string> = {
    pending: 'Ждут решения', new: 'Ещё не разобраны', accepted: 'Приняты', corrected: 'Исправлены', rejected: 'Отклонены',
  }
  if (filters.state) parts.push(state[filters.state] ?? '')
  if (filters.review) parts.push('Проверить вручную')
  if (filters.overdue) parts.push('Просрочены')
  return parts.filter(Boolean).join(', ') || 'Все письма'
})

const SUMMARY: Array<{ key: string; label: string; hint: string; icon: IconName; filter: Record<string, string>; tone?: string }> = [
  { key: 'pending', label: 'Ждут решения', hint: 'черновик готов, нужно принять или поправить', icon: 'decide', filter: { state: 'pending' } },
  { key: 'high', label: 'Срочные', hint: 'есть срок или серьёзные последствия', icon: 'flame', filter: { priority: 'high' }, tone: 'red' },
  { key: 'overdue', label: 'Просрочены', hint: 'срок реакции уже прошёл', icon: 'alarm', filter: { overdue: '1' }, tone: 'red' },
  { key: 'needs_review', label: 'Проверить вручную', hint: 'помощник не уверен или есть риск', icon: 'flag', filter: { review: '1' } },
]
const summaryValue = (key: string) => (key === 'pending' ? f('state:pending') : counts.value[key] ?? 0)
const summaryActive = (filter: Record<string, string>) =>
  Object.entries(filter).every(([k, v]) => filters[k as FilterKey] === v)

const TABS: Array<{ key: string; label: string; icon: IconName }> = [
  { key: '', label: 'Все', icon: 'layers' },
  { key: 'sale', label: 'Продажи', icon: 'sale' },
  { key: 'complaint', label: 'Жалобы', icon: 'complaint' },
  { key: 'question', label: 'Вопросы', icon: 'question' },
  { key: 'spam', label: 'Спам', icon: 'spam' },
]
const CATEGORY_ICON: Record<string, IconName> = { sale: 'sale', complaint: 'complaint', question: 'question', spam: 'spam' }
const tabCount = (key: string) => (key ? f(`category:${key}`) : counts.value.total ?? 0)

const filtered = computed(() =>
  (['priority', 'state', 'review', 'source', 'overdue', 'q', 'category'] as FilterKey[]).some((k) => filters[k]),
)

function reset() {
  Object.assign(filters, EMPTY_FILTERS)
}

async function startJob() {
  jobError.value = ''
  try {
    await api.post<{ job: Job }>('/api/jobs', {})
    await loadMail(true)
  } catch (e) {
    jobError.value = e instanceof ApiError ? e.message : 'Не удалось запустить разбор'
  }
}

function open(lead: LeadSummary) {
  router.push({ path: `/leads/${encodeURIComponent(lead.key)}`, query: route.query })
}
function close() {
  router.push({ path: '/leads', query: route.query })
}

// --- выгрузка ---
const exportOpen = ref(false)
const FORMATS: Array<{ key: string; label: string; hint: string }> = [
  { key: 'xlsx', label: 'Excel', hint: 'таблица для фильтров и отчётов' },
  { key: 'pdf', label: 'PDF', hint: 'для печати и пересылки' },
  { key: 'docx', label: 'Word', hint: 'документ для правки' },
  { key: 'json', label: 'JSON', hint: 'для загрузки в другие системы' },
]
function download(format: string) {
  exportOpen.value = false
  window.location.href = `/api/leads/export?${queryString({ format })}`
}
function closeMenuOnBlur(event: FocusEvent) {
  const box = event.currentTarget as HTMLElement
  if (!box.contains(event.relatedTarget as Node | null)) exportOpen.value = false
}

// --- отображение строк ---
function subject(lead: LeadSummary): string {
  if (lead.subject) return lead.subject
  const first = (lead.text ?? '').split('\n')[0] ?? ''
  return first.startsWith('Тема: ') ? first.slice(6) : first
}
function preview(lead: LeadSummary): string {
  const text = (lead.text ?? '').replace(/^Тема: .*\n?/, '').replace(/\s+/g, ' ').trim()
  return text === subject(lead) ? '' : text
}
function initials(name: string | null): string {
  const words = (name ?? '').replace(/[^\p{L}\s]/gu, '').split(/\s+/).filter(Boolean)
  return words.map((w) => w[0]).slice(0, 2).join('').toUpperCase() || '?'
}
const PALETTE = ['#25364f', '#3f5f8a', '#5b4b7a', '#2f6b62', '#7a4b3a', '#4a5568']
function avatarColor(name: string | null): string {
  let hash = 0
  for (const ch of name ?? '') hash = (hash * 31 + ch.charCodeAt(0)) >>> 0
  return PALETTE[hash % PALETTE.length] ?? '#25364f'
}
function when(date: string | null): string {
  if (!date) return '—'
  const d = new Date(`${date}T00:00:00`)
  if (Number.isNaN(d.getTime())) return date
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const days = Math.round((today.getTime() - d.getTime()) / 86400000)
  if (days === 0) return 'Сегодня'
  if (days === 1) return 'Вчера'
  return d.toLocaleDateString('ru-RU', {
    day: 'numeric',
    month: 'short',
    year: d.getFullYear() === today.getFullYear() ? undefined : 'numeric',
  })
}
function due(value: string | null): string {
  if (!value) return '—'
  return new Date(value).toLocaleString('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}
const STATE_TONE: Record<string, string> = { new: 'gray', pending: 'info', accepted: 'low', corrected: 'low', rejected: 'gray' }
const isOpen = (lead: LeadSummary) => lead.state === 'new' || lead.state === 'pending'

function onKey(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    if (selected.value) close()
    exportOpen.value = false
  }
}
onMounted(() => {
  loadMail(!!mail.data)
  window.addEventListener('keydown', onKey)
})
onUnmounted(() => window.removeEventListener('keydown', onKey))
const PRIORITY_OPTIONS = [
  { value: '', label: 'Любая срочность' },
  { value: 'high', label: 'Высокая', tone: 'high' },
  { value: 'medium', label: 'Средняя', tone: 'medium' },
  { value: 'low', label: 'Низкая', tone: 'low' },
]
const STATE_OPTIONS = [
  { value: '', label: 'Любое состояние' },
  { value: 'new', label: 'Ещё не разобраны' },
  { value: 'pending', label: 'Ждут решения' },
  { value: 'accepted', label: 'Приняты' },
  { value: 'corrected', label: 'Исправлены' },
  { value: 'rejected', label: 'Отклонены' },
]
</script>

<template>
  <div class="page mail">
    <div class="page-head">
      <h1>{{ title }}</h1>
      <div class="actions">
        <div class="menu" @focusout="closeMenuOnBlur">
          <button :aria-expanded="exportOpen" aria-haspopup="menu" @click="exportOpen = !exportOpen">
            <Icon name="download" /> <span class="hide-mobile">Выгрузить</span>
          </button>
          <div v-if="exportOpen" class="menu-pop" role="menu">
            <p class="menu-title small muted">Выгрузить {{ filtered ? 'то, что на экране' : 'все письма' }}</p>
            <button v-for="fmt in FORMATS" :key="fmt.key" role="menuitem" class="menu-item" @click="download(fmt.key)">
              <b>{{ fmt.label }}</b><span class="small muted">{{ fmt.hint }}</span>
            </button>
          </div>
        </div>
        <button
          class="primary"
          :disabled="!!job || !counts.new"
          :title="counts.new ? 'Помощник определит категорию, срочность и подготовит черновики' : 'Новых писем нет'"
          @click="startJob"
        >
          <Icon name="run" />
          {{ job ? 'Разбор идёт…' : counts.new ? `Разобрать новые (${counts.new})` : 'Новых нет' }}
        </button>
      </div>
    </div>

    <div v-if="jobError" class="alert error"><Icon name="info" /> {{ jobError }}</div>
    <div v-if="job" class="job card">
      <span class="spinner"></span>
      <div class="grow">
        <b>Помощник разбирает письма</b>
        <span v-if="job.progress.total" class="muted small"> — готово {{ job.progress.done }} из {{ job.progress.total }}</span>
        <div v-if="job.progress.total" class="progress"><div :style="{ width: jobPercent + '%' }"></div></div>
      </div>
      <RouterLink class="small" to="/jobs">Подробнее</RouterLink>
    </div>

    <section v-if="data" class="summary" aria-label="Сводка">
      <button
        v-for="s in SUMMARY"
        :key="s.key"
        class="stat"
        :class="[s.tone, { active: summaryActive(s.filter) }]"
        :aria-pressed="summaryActive(s.filter)"
        @click="summaryActive(s.filter) ? applyFolder({}) : applyFolder(s.filter)"
      >
        <span class="stat-label"><Icon :name="s.icon" size="1.05rem" /> {{ s.label }}</span>
        <span class="stat-value num">{{ summaryValue(s.key) }}</span>
        <span class="stat-hint small">{{ s.hint }}</span>
      </button>
    </section>

    <div class="board card">
      <div class="tabs" role="tablist" aria-label="Категория">
        <button
          v-for="tab in TABS"
          :key="tab.key"
          role="tab"
          class="tab"
          :class="{ active: filters.category === tab.key }"
          :aria-selected="filters.category === tab.key"
          @click="filters.category = tab.key"
        >
          <Icon :name="tab.icon" size="1.05rem" /> {{ tab.label }}
          <span class="tab-count num">{{ tabCount(tab.key) }}</span>
        </button>
      </div>

      <div class="toolbar">
        <UiSelect v-model="filters.priority" class="flt" :options="PRIORITY_OPTIONS" aria-label="Срочность" />
        <UiSelect v-model="filters.state" class="flt" :options="STATE_OPTIONS" aria-label="Состояние" />
        <span class="grow"></span>
        <span v-if="data" class="small muted count-label">Показано: <b class="num">{{ data.leads.length }}</b></span>
        <button v-if="filtered" class="ghost" @click="reset"><Icon name="close" /> Сбросить</button>
      </div>

      <div v-if="mail.loading && !data" class="empty"><span class="spinner"></span> Загружаю письма…</div>
      <div v-else-if="mail.error" class="alert error">
        <Icon name="info" /> {{ mail.error }} <button class="link" @click="loadMail()">Повторить</button>
      </div>
      <div v-else-if="data && !data.leads.length" class="empty">
        <Icon name="inbox" size="2.4rem" />
        <p v-if="filtered">В этой папке писем нет. <button class="link" @click="reset">Показать все письма</button></p>
        <p v-else>Писем пока нет. Подключите почтовый ящик в разделе <RouterLink to="/connectors">«Почта и сервисы»</RouterLink>.</p>
      </div>
      <div v-else-if="data" class="table-wrap"><table class="list">
        <thead>
          <tr>
            <th class="c-from">Отправитель</th>
            <th class="c-subject">Письмо</th>
            <th class="c-cat">Категория</th>
            <th class="c-pri">Срочность</th>
            <th class="c-state">Состояние</th>
            <th class="c-who">Ответственный</th>
            <th class="c-due">Ответить до</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="lead in data.leads"
            :key="lead.key"
            tabindex="0"
            :class="{ urgent: lead.priority === 'high' && isOpen(lead), done: !isOpen(lead) }"
            :aria-label="`Письмо от ${lead.name}: ${subject(lead)}`"
            @click="open(lead)"
            @keydown.enter="open(lead)"
          >
            <td class="c-from">
              <div class="from-wrap">
                <span class="avatar" :style="{ background: avatarColor(lead.name) }" aria-hidden="true">{{ initials(lead.name) }}</span>
                <span class="from">
                  <b class="name">{{ lead.name || 'Без имени' }}</b>
                  <span class="contact small muted">
                    <Icon :name="lead.channel === 'telegram' ? 'telegram' : 'mail'" size="0.9rem" />
                    <span class="contact-text" :title="lead.contact ?? ''">{{ lead.contact || 'контакт не указан' }}</span>
                  </span>
                </span>
              </div>
            </td>
            <td class="c-subject">
              <span class="subject">{{ subject(lead) || '(без темы)' }}</span>
              <span v-if="preview(lead)" class="preview small muted">{{ preview(lead) }}</span>
              <span class="when small muted"><Icon name="calendar" size="0.85rem" /> {{ when(lead.date) }}</span>
            </td>
            <td class="c-cat">
              <span v-if="lead.category" class="cat"><Icon :name="CATEGORY_ICON[lead.category] ?? 'question'" size="1rem" /> {{ CATEGORY[lead.category] }}</span>
              <span v-else class="muted small">—</span>
            </td>
            <td class="c-pri">
              <span v-if="lead.priority" class="badge" :class="lead.priority">{{ PRIORITY[lead.priority] }}</span>
            </td>
            <td class="c-state">
              <span class="badge" :class="STATE_TONE[lead.state]">{{ lead.state_title }}</span>
              <span v-if="lead.needs_review" class="flag" :title="lead.review_reasons.map((r) => r.text).join('\n')">
                <Icon name="flag" size="1rem" label="Проверить вручную" />
              </span>
              <span v-if="lead.overdue" class="late-icon" title="Срок реакции прошёл"><Icon name="alarm" size="1rem" label="Просрочено" /></span>
            </td>
            <td class="c-who small">{{ lead.assignee || '—' }}</td>
            <td class="c-due small num" :class="{ late: lead.overdue }">{{ due(lead.due_at) }}</td>
          </tr>
        </tbody>
      </table></div>
    </div>

    <div v-if="selected" class="lead-modal" role="dialog" aria-modal="true" aria-label="Письмо" @click.self="close">
      <div class="lead-dialog">
        <LeadCard :lead-key="selected" @close="close" @changed="loadMail(true)" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.page.mail { max-width: none; }
.page-head h1 { min-width: 0; overflow-wrap: anywhere; }
.job { display: flex; align-items: center; gap: 0.9rem; margin-bottom: 1rem; }
.job .progress { margin-top: 0.45rem; }

/* Сводка: одна полоса из четырёх показателей, каждый — кнопка-фильтр. */
.summary {
  display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); margin-bottom: 1.25rem;
  background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); box-shadow: var(--shadow);
  overflow: hidden;
}
.stat {
  display: flex; flex-direction: column; align-items: flex-start; justify-content: flex-start; gap: 0.15rem; text-align: left;
  border: 0; border-radius: 0; background: none; padding: 1rem 1.25rem 1.05rem; min-height: 0; white-space: normal;
  border-right: 1px solid var(--line); position: relative;
}
.stat:last-child { border-right: 0; }
.stat:hover:not(:disabled) { background: var(--surface-2); border-color: var(--line); }
.stat.active { background: var(--accent-soft); }
.stat.active::after { content: ''; position: absolute; left: 0; right: 0; bottom: 0; height: 3px; background: var(--accent); }
.stat-label { display: flex; align-items: center; gap: 0.45rem; color: var(--muted); font-weight: 520; }
.stat-value { font-size: 2.1rem; font-weight: 650; line-height: 1.15; letter-spacing: -0.02em; color: var(--text); }
.stat.red .stat-value { color: var(--brand-red); }
.stat-hint { color: var(--muted); font-weight: 400; }

.board { padding: 0; overflow: visible; }
.table-wrap { overflow-x: auto; border-radius: 0 0 var(--radius) var(--radius); }
.tabs { display: flex; gap: 0.25rem; padding: 0 0.75rem; border-bottom: 1px solid var(--line); overflow-x: auto; scrollbar-width: none; }
.tab {
  border: 0; border-radius: 0; background: none; padding: 0.85rem 0.75rem; min-height: 0; color: var(--muted);
  border-bottom: 2px solid transparent; margin-bottom: -1px; font-weight: 520;
}
.tab:hover:not(:disabled) { background: none; color: var(--text); border-color: transparent; border-bottom: 2px solid var(--line-strong); }
.tab.active, .tab.active:hover:not(:disabled) { color: var(--accent); border-bottom: 2px solid var(--accent); font-weight: 640; }
.tab-count {
  font-size: 0.78rem; background: var(--surface-2); box-shadow: inset 0 0 0 1px var(--line);
  border-radius: 99px; padding: 0 0.45rem; color: var(--muted);
}
.toolbar { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; padding: 0.75rem 1rem; border-bottom: 1px solid var(--line); }
.toolbar .flt { width: 12.5rem; }

.list th { background: var(--surface-2); padding: 0.6rem 1rem; white-space: nowrap; }
.list td { padding: 0.8rem 1rem; vertical-align: middle; }
.list tbody tr { cursor: pointer; transition: background-color 0.12s; }
.list tbody tr:last-child td { border-bottom: 0; }
.list tbody tr:hover, .list tbody tr:focus-visible { background: var(--surface-2); outline: none; }
.list tbody tr:focus-visible { box-shadow: inset 0 0 0 2px var(--focus); }
/* Срочное письмо отмечено красной линией-«маршрутом», как штрих логотипа. */
.list tbody tr.urgent td:first-child { box-shadow: inset 3px 0 0 var(--brand-red); }
.list tbody tr.done .name, .list tbody tr.done .subject { font-weight: 450; color: var(--muted); }
.c-from { min-width: 15rem; }
.from-wrap { display: flex; align-items: center; gap: 0.75rem; }
.avatar {
  width: 2.4rem; height: 2.4rem; border-radius: 50%; display: grid; place-items: center; color: #fff;
  font-size: 0.82rem; font-weight: 650; flex: none;
}
.from { display: flex; flex-direction: column; min-width: 0; }
.name { font-weight: 620; }
.contact { display: flex; align-items: center; gap: 0.3rem; min-width: 0; }
.contact-text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 15rem; }
.from-wrap { min-width: 0; }
.c-subject { width: 100%; min-width: 16rem; max-width: 0; }
.subject, .preview { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.subject { font-weight: 600; }
.when { display: inline-flex; align-items: center; gap: 0.3rem; margin-top: 0.15rem; }
.cat { display: inline-flex; align-items: center; gap: 0.35rem; white-space: nowrap; }
.cat :deep(.icon) { color: var(--muted); }
.c-state { white-space: nowrap; }
.flag { color: var(--warn); margin-left: 0.35rem; }
.late-icon { color: var(--brand-red); margin-left: 0.35rem; }
td.late { color: var(--brand-red); font-weight: 600; }
.c-who, .c-due { white-space: nowrap; }

/* Выгрузка: меню форматов. */
.menu { position: relative; }
.menu-pop {
  position: absolute; right: 0; top: calc(100% + 0.4rem); z-index: 20; width: 17rem; padding: 0.4rem;
  background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); box-shadow: var(--shadow-pop);
}
.menu-title { padding: 0.35rem 0.6rem 0.25rem; margin: 0; }
.menu-item {
  width: 100%; flex-direction: column; align-items: flex-start; gap: 0; border: 0; background: none;
  padding: 0.5rem 0.6rem; min-height: 0; white-space: normal; text-align: left;
}
.menu-item:hover:not(:disabled) { background: var(--accent-soft); border: 0; }

/* Письмо — во всплывающем окне поверх списка. */
.lead-modal {
  position: fixed; inset: 0; z-index: 45; background: rgb(15 21 32 / 0.5);
  display: grid; place-items: start center; padding: 2rem 1rem; overflow: auto;
}
.lead-dialog { width: min(76rem, 100%); }

/* «Ответить до» видно от 1600 px, «Ответственный» — от 1520 px, категория — от 1100 px. */
@media (max-width: 1600px) {
  .c-due { display: none; }
}
@media (max-width: 1520px) {
  .c-who { display: none; }
}
@media (max-width: 1100px) {
  .c-cat { display: none; }
  .summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .stat:nth-child(2) { border-right: 0; }
  .stat:nth-child(-n + 2) { border-bottom: 1px solid var(--line); }
}
/* Телефон: таблица превращается в карточки писем. */
@media (max-width: 760px) {
  .stat { padding: 0.8rem 0.9rem; }
  .stat-value { font-size: 1.7rem; }
  .stat-hint { display: none; }
  .toolbar .flt { width: auto; flex: 1 1 40%; }
  .toolbar .count-label { display: none; }
  .list thead { display: none; }
  .list, .list tbody { display: block; }
  .table-wrap { overflow: visible; }
  .list tbody tr {
    display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 0.2rem 0.7rem; padding: 0.85rem 0.9rem;
    border-bottom: 1px solid var(--line);
    grid-template-areas: 'from pri' 'subj subj' 'state state';
  }
  .list td { display: block; padding: 0; border: 0; }
  .list td.c-cat, .list td.c-who, .list td.c-due { display: none; }
  .list tbody tr.urgent { box-shadow: inset 3px 0 0 var(--brand-red); }
  .list tbody tr.urgent td:first-child { box-shadow: none; }
  .c-from { grid-area: from; min-width: 0; }
  .avatar { width: 2rem; height: 2rem; font-size: 0.75rem; }
  .c-pri { grid-area: pri; }
  .c-subject { grid-area: subj; min-width: 0; max-width: none; margin-top: 0.35rem; }
  .c-state { grid-area: state; margin-top: 0.4rem; }
  .lead-modal { padding: 0; }
}
</style>
