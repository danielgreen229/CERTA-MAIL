<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, ApiError, CATEGORY, PRIORITY, formatDate, type Job, type LeadSummary } from '../api'
import LeadCard from '../components/LeadCard.vue'

interface ListResponse {
  leads: LeadSummary[]
  counts: Record<string, number>
  active_job: Job | null
}

const route = useRoute()
const router = useRouter()
const data = ref<ListResponse | null>(null)
const loading = ref(true)
const error = ref('')
const jobError = ref('')
const filters = reactive({
  q: String(route.query.q ?? ''),
  category: String(route.query.category ?? ''),
  priority: String(route.query.priority ?? ''),
  state: String(route.query.state ?? ''),
  review: String(route.query.review ?? ''),
})
const selected = computed(() => (route.params.key ? String(route.params.key) : null))
let timer: number | undefined

async function load(silent = false) {
  if (!silent) loading.value = true
  error.value = ''
  const params = new URLSearchParams(Object.entries(filters).filter(([, v]) => v))
  try {
    data.value = await api.get<ListResponse>(`/api/leads?${params}`)
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось загрузить заявки'
  } finally {
    loading.value = false
  }
}

let debounce: number | undefined
watch(filters, () => {
  window.clearTimeout(debounce)
  debounce = window.setTimeout(() => {
    const query = Object.fromEntries(Object.entries(filters).filter(([, v]) => v))
    router.replace({ path: route.path, query })
    load()
  }, 250)
})

async function startJob() {
  jobError.value = ''
  try {
    await api.post<{ job: Job }>('/api/jobs', {})
    await load(true)
  } catch (e) {
    jobError.value = e instanceof ApiError ? e.message : 'Не удалось запустить обработку'
  }
}

function open(lead: LeadSummary) {
  router.push({ path: `/leads/${encodeURIComponent(lead.key)}`, query: route.query })
}

function close() {
  router.push({ path: '/leads', query: route.query })
}

function reset() {
  Object.assign(filters, { q: '', category: '', priority: '', state: '', review: '' })
}

const job = computed(() => data.value?.active_job ?? null)
const jobPercent = computed(() => {
  const p = job.value?.progress
  return p && p.total ? Math.round(((p.done ?? 0) / p.total) * 100) : 0
})

onMounted(() => {
  load()
  // Пока идёт фоновая обработка, список обновляется сам; закрытие страницы её не прерывает.
  timer = window.setInterval(() => {
    if (job.value) load(true)
  }, 4000)
})
onUnmounted(() => window.clearInterval(timer))
</script>

<template>
  <main class="page">
    <div class="layout" :class="{ 'with-card': selected }">
      <section class="list-pane">
        <div class="row" style="justify-content: space-between">
          <h1>Заявки</h1>
          <button class="primary" :disabled="!!job" @click="startJob">
            {{ job ? 'Обработка идёт…' : 'Обработать новые' }}
          </button>
        </div>
        <div v-if="jobError" class="alert error">{{ jobError }}</div>
        <div v-if="job" class="card job">
          <div class="row">
            <span class="spinner"></span>
            <strong>Задача {{ job.id }}</strong>
            <span class="muted small">
              {{ job.state === 'queued' ? 'в очереди' : 'идёт' }} · попытка {{ job.attempts }} из {{ job.max_attempts }}
            </span>
            <RouterLink class="small" to="/jobs">подробнее</RouterLink>
          </div>
          <div v-if="job.progress.total" style="margin-top: 8px">
            <div class="progress"><div :style="{ width: jobPercent + '%' }"></div></div>
            <div class="small muted">записано {{ job.progress.done }} из {{ job.progress.total }}</div>
          </div>
        </div>

        <div v-if="data" class="counts row small">
          <span>Всего: <b>{{ data.counts.total }}</b></span>
          <span>Ждут агента: <b>{{ data.counts.new }}</b></span>
          <span>Ждут решения: <b>{{ data.counts.pending }}</b></span>
          <span>На проверку: <b>{{ data.counts.needs_review }}</b></span>
          <span>Срочных: <b>{{ data.counts.high }}</b></span>
          <span>Просрочено: <b>{{ data.counts.overdue }}</b></span>
        </div>

        <div class="filters">
          <input v-model="filters.q" type="search" placeholder="Поиск: текст, имя, контакт, номер" aria-label="Поиск" />
          <select v-model="filters.category" aria-label="Категория">
            <option value="">Все категории</option>
            <option v-for="(title, key) in CATEGORY" :key="key" :value="key">{{ title }}</option>
          </select>
          <select v-model="filters.priority" aria-label="Срочность">
            <option value="">Любая срочность</option>
            <option v-for="(title, key) in PRIORITY" :key="key" :value="key">{{ title }}</option>
          </select>
          <select v-model="filters.state" aria-label="Состояние">
            <option value="">Любое состояние</option>
            <option value="new">Ждёт агента</option>
            <option value="pending">Ждёт решения</option>
            <option value="accepted">Принято</option>
            <option value="corrected">Исправлено</option>
            <option value="rejected">Отклонено</option>
          </select>
          <label class="check"><input v-model="filters.review" type="checkbox" true-value="1" false-value="" /> Только на проверку</label>
        </div>

        <div v-if="loading" class="empty"><span class="spinner"></span> Загрузка…</div>
        <div v-else-if="error" class="alert error">
          {{ error }} <button @click="load()">Повторить</button>
        </div>
        <div v-else-if="data && !data.leads.length" class="empty">
          <template v-if="data.counts.total">Нет заявок по выбранным условиям. <button @click="reset">Сбросить фильтры</button></template>
          <template v-else>Заявок пока нет.</template>
        </div>
        <ul v-else-if="data" class="leads">
          <li
            v-for="lead in data.leads"
            :key="lead.key"
            :class="{ active: selected === lead.key }"
            tabindex="0"
            @click="open(lead)"
            @keydown.enter="open(lead)"
          >
            <div class="row">
              <strong>№ {{ lead.id }}</strong>
              <span class="muted small">{{ formatDate(lead.date) }} · {{ lead.channel }}</span>
              <span class="grow"></span>
              <span v-if="lead.priority" class="badge" :class="lead.priority">{{ PRIORITY[lead.priority] }}</span>
              <span v-if="lead.category" class="badge gray">{{ CATEGORY[lead.category] }}</span>
            </div>
            <div class="text">{{ lead.name }} — {{ lead.text }}</div>
            <div class="row small">
              <span class="badge" :class="{ gray: lead.state !== 'pending' }">{{ lead.state_title }}</span>
              <span v-if="lead.needs_review" class="badge medium" :title="lead.review_reasons.map((r) => r.text).join('\n')">
                на проверку: {{ lead.review_reasons.length }}
              </span>
              <span v-if="lead.overdue" class="badge high">срок реакции прошёл</span>
              <span v-if="lead.assignee" class="muted">{{ lead.assignee }}</span>
            </div>
          </li>
        </ul>
      </section>
      <section v-if="selected" class="card-pane">
        <LeadCard :lead-key="selected" @close="close" @changed="load(true)" />
      </section>
    </div>
  </main>
</template>

<style scoped>
.layout { display: grid; grid-template-columns: 1fr; gap: 16px; }
.layout.with-card { grid-template-columns: minmax(320px, 2fr) 3fr; }
.job { margin: 8px 0; }
.counts { gap: 14px; margin: 8px 0; color: var(--muted); }
.filters { display: grid; grid-template-columns: 2fr 1fr 1fr 1fr auto; gap: 8px; margin: 8px 0 12px; align-items: center; }
.check { display: flex; gap: 6px; align-items: center; margin: 0; white-space: nowrap; color: var(--text); font-size: 14px; }
.check input { width: auto; min-height: 0; }
.leads { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
.leads li {
  background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius);
  padding: 10px 12px; cursor: pointer; display: flex; flex-direction: column; gap: 6px;
}
.leads li:hover, .leads li:focus { border-color: var(--accent); outline: none; }
.leads li.active { border-color: var(--accent); box-shadow: 0 0 0 2px var(--accent-soft); }
.text { overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; }
.card-pane { position: sticky; top: 64px; align-self: start; max-height: calc(100vh - 80px); overflow: auto; }
@media (max-width: 1100px) {
  .filters { grid-template-columns: 1fr 1fr; }
  .filters input[type='search'] { grid-column: 1 / -1; }
}
@media (max-width: 900px) {
  .layout.with-card { grid-template-columns: 1fr; }
  .layout.with-card .list-pane { display: none; }
  .card-pane { position: static; max-height: none; }
}
</style>
