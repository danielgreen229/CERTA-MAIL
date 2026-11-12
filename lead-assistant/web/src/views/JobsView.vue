<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api, ApiError, type Job } from '../api'
import Icon from '../components/Icon.vue'
import { loadMail, mail } from '../mailbox'
import { can } from '../session'

/** «Разбор писем»: что делает помощник сейчас и что сделал раньше — без внутренних терминов. */
const jobs = ref<Job[]>([])
const loading = ref(true)
const error = ref('')
const actionError = ref('')
const mailCheck = ref<{ enabled?: boolean; interval_seconds?: number; auto_process?: boolean } | null>(null)
let timer: number | undefined

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    jobs.value = (await api.get<{ jobs: Job[] }>('/api/jobs')).jobs
    error.value = ''
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось загрузить историю разбора'
  } finally {
    loading.value = false
  }
}

async function start() {
  actionError.value = ''
  try {
    await api.post('/api/jobs', {})
    await Promise.all([load(true), loadMail(true)])
  } catch (e) {
    actionError.value = e instanceof ApiError ? e.message : 'Не удалось запустить разбор'
  }
}

async function cancel(job: Job) {
  try {
    await api.post(`/api/jobs/${job.id}/cancel`)
    await load(true)
  } catch (e) {
    actionError.value = e instanceof ApiError ? e.message : 'Не удалось отменить'
  }
}

const current = computed(() => jobs.value.find((j) => j.state === 'queued' || j.state === 'running') ?? null)
const fresh = computed(() => mail.data?.counts.new ?? 0)
const percent = (job: Job) =>
  job.progress.total ? Math.round(((job.progress.done ?? 0) / job.progress.total) * 100) : 0

/** История: настоящие разборы отдельно, пустые проверки («новых не было») — одной строкой. */
const history = computed(() => {
  const items: Array<{ kind: 'job'; job: Job } | { kind: 'idle'; count: number; last: string }> = []
  for (const job of jobs.value) {
    if (job === current.value) continue
    const empty = job.state === 'done' && !job.progress.total
    const last = items[items.length - 1]
    if (empty && last?.kind === 'idle') last.count += 1
    else if (empty) items.push({ kind: 'idle', count: 1, last: job.finished_at ?? job.created_at })
    else items.push({ kind: 'job', job })
  }
  return items
})

const ERRORS: Record<string, string> = {
  WORKER_LOST: 'Обработчик перезапускался — разбор продолжился с того же места.',
  LLM_SETUP: 'Модель не запустилась. Проверьте раздел «Настройки» → «Модель».',
  WORKER_ERROR: 'Разбор прервался из-за внутренней ошибки. Запустите его ещё раз.',
  TIMEOUT: 'Модель не уложилась во время. Неразобранные письма возьмёт следующий запуск.',
}
const explain = (job: Job) => (job.error ? ERRORS[job.error.code] ?? job.error.message ?? job.error.code : '')

function when(value: string | null): string {
  if (!value) return ''
  const d = new Date(value)
  const today = new Date()
  const same = d.toDateString() === today.toDateString()
  const time = d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
  return same ? `Сегодня, ${time}` : `${d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })}, ${time}`
}
function duration(job: Job): string {
  if (!job.started_at || !job.finished_at) return ''
  const s = Math.max(1, Math.round((Date.parse(job.finished_at) - Date.parse(job.started_at)) / 1000))
  return s < 60 ? `${s} с` : `${Math.floor(s / 60)} мин ${s % 60} с`
}
const lastLine = (job: Job) => (job.progress.log ?? []).filter((l) => l.trim()).slice(-1)[0] ?? ''
const leadLink = (id: unknown) => `/leads/${encodeURIComponent(JSON.stringify(id))}`

onMounted(async () => {
  load()
  api.get<Record<string, unknown>>('/api/settings')
    .then((s) => (mailCheck.value = (s.mail_check as typeof mailCheck.value) ?? null))
    .catch(() => undefined)
  timer = window.setInterval(() => load(true), 4000)
})
onUnmounted(() => window.clearInterval(timer))
</script>

<template>
  <div class="page">
    <div class="page-head">
      <h1><Icon name="agent" /> Разбор писем</h1>
      <div class="actions">
        <button class="primary" :disabled="!!current || !fresh" @click="start">
          <Icon name="run" /> {{ current ? 'Разбор идёт…' : fresh ? `Разобрать новые (${fresh})` : 'Новых писем нет' }}
        </button>
      </div>
      <p class="lead">
        Помощник читает новые письма, определяет категорию и срочность и готовит черновик ответа.
        Ответ клиенту уходит только после вашего решения в «Почте».
      </p>
    </div>

    <div v-if="actionError" class="alert error"><Icon name="info" /> {{ actionError }}</div>

    <section class="status card">
      <div class="status-item">
        <Icon name="refresh" size="1.6rem" />
        <div>
          <b>Почта проверяется {{ mailCheck?.enabled === false ? 'вручную' : 'автоматически' }}</b>
          <p class="small muted">
            <template v-if="mailCheck?.enabled !== false">
              Раз в {{ Math.round((mailCheck?.interval_seconds ?? 60) / 60) || 1 }} мин —
              {{ mailCheck?.auto_process === false ? 'письма ждут ручного запуска' : 'новые письма сразу разбираются' }}.
            </template>
            <template v-else>Нажмите «Разобрать новые», когда придут письма.</template>
          </p>
        </div>
      </div>
      <div class="status-item">
        <Icon name="hourglass" size="1.6rem" />
        <div>
          <b>Ждут разбора: <span class="num">{{ fresh }}</span></b>
          <p class="small muted">{{ fresh ? 'Письма пришли и ещё не прочитаны помощником.' : 'Все письма разобраны.' }}</p>
        </div>
      </div>
      <div class="status-item">
        <Icon name="decide" size="1.6rem" />
        <div>
          <b>Ждут вашего решения: <span class="num">{{ mail.data?.counts.pending ?? 0 }}</span></b>
          <p class="small muted"><RouterLink to="/leads?state=pending">Открыть в «Почте»</RouterLink></p>
        </div>
      </div>
    </section>

    <section v-if="current" class="card now">
      <div class="row">
        <span class="spinner"></span>
        <b>{{ current.state === 'queued' ? 'Разбор скоро начнётся' : 'Помощник разбирает письма' }}</b>
        <span class="grow"></span>
        <button v-if="current.state === 'queued'" class="ghost" @click="cancel(current)"><Icon name="close" /> Отменить</button>
      </div>
      <template v-if="current.progress.total">
        <div class="progress big"><div :style="{ width: percent(current) + '%' }"></div></div>
        <p class="small"><b class="num">{{ current.progress.done }}</b> из <span class="num">{{ current.progress.total }}</span> готово</p>
      </template>
      <p v-if="lastLine(current)" class="small muted log">{{ lastLine(current) }}</p>
      <p class="small muted">Страницу можно закрыть — разбор продолжится сам.</p>
    </section>

    <h2 class="section-title">Последние разборы</h2>
    <div v-if="loading" class="empty"><span class="spinner"></span> Загружаю…</div>
    <div v-else-if="error" class="alert error"><Icon name="info" /> {{ error }} <button class="link" @click="load()">Повторить</button></div>
    <div v-else-if="!history.length" class="empty"><Icon name="agent" size="2.2rem" /><p>Разборов ещё не было.</p></div>
    <ol v-else class="timeline">
      <li v-for="(item, i) in history" :key="item.kind === 'job' ? item.job.id : `idle-${i}`" :class="item.kind === 'job' ? item.job.state : 'idle'">
        <template v-if="item.kind === 'idle'">
          <span class="dot"></span>
          <div class="muted small">
            {{ when(item.last) }} — {{ item.count === 1 ? 'проверка' : `${item.count} проверок` }} без новых писем
          </div>
        </template>
        <template v-else>
          <span class="dot"></span>
          <div class="entry card">
            <div class="row">
              <b>{{ when(item.job.finished_at ?? item.job.created_at) }}</b>
              <span v-if="item.job.state === 'done'" class="badge low"><Icon name="check" size="0.9rem" /> Разобрано {{ item.job.progress.done ?? 0 }} из {{ item.job.progress.total }}</span>
              <span v-else-if="item.job.state === 'failed'" class="badge high"><Icon name="close" size="0.9rem" /> Не завершён</span>
              <span v-else class="badge gray">Отменён</span>
              <span v-if="duration(item.job)" class="small muted">за {{ duration(item.job) }}</span>
            </div>
            <p v-if="explain(item.job)" class="small" :class="item.job.state === 'failed' ? 'err' : 'muted'">{{ explain(item.job) }}</p>
            <div v-if="item.job.summary?.urgent?.length" class="urgent">
              <p class="small"><Icon name="flame" size="1rem" /> <b>Срочные — начните с них:</b></p>
              <ul>
                <li v-for="u in item.job.summary.urgent" :key="String(u.id)" class="small">
                  <RouterLink :to="leadLink(u.id)">Письмо № {{ u.id }}</RouterLink> — {{ u.basis }}
                  <span v-if="u.next" class="muted">Что сделать: {{ u.next }}</span>
                </li>
              </ul>
            </div>
            <details v-if="can('admin')" class="tech small">
              <summary>Технические подробности</summary>
              <p class="muted">
                Задача {{ item.job.id }}; попыток {{ item.job.attempts }} из {{ item.job.max_attempts }}<template v-if="item.job.summary?.model">; модель {{ item.job.summary.model }}</template>.
              </p>
              <pre v-if="item.job.summary?.text" class="muted">{{ item.job.summary.text }}</pre>
            </details>
          </div>
        </template>
      </li>
    </ol>
  </div>
</template>

<style scoped>
.status { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); padding: 0; margin-bottom: 1.25rem; }
.status-item { display: flex; gap: 0.85rem; align-items: flex-start; padding: 1.1rem 1.25rem; border-right: 1px solid var(--line); }
.status-item:last-child { border-right: 0; }
.status-item > :deep(.icon) { color: var(--brand-navy); margin-top: 0.1rem; }
:root[data-theme='dark'] .status-item > :deep(.icon) { color: var(--accent); }
.status-item p { margin: 0.2rem 0 0; }
.now { margin-bottom: 1.25rem; border-left: 4px solid var(--accent); }
.progress.big { height: 0.7rem; margin: 0.8rem 0 0.4rem; }
.log { font-family: inherit; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.section-title { margin: 1.5rem 0 0.9rem; }
.timeline { list-style: none; margin: 0; padding: 0 0 0 1.4rem; border-left: 2px solid var(--line); display: grid; gap: 0.9rem; }
.timeline li { position: relative; }
.dot { position: absolute; left: calc(-1.4rem - 6px); top: 0.55rem; width: 10px; height: 10px; border-radius: 50%; background: var(--line-strong); box-shadow: 0 0 0 3px var(--bg); }
.timeline li.done .dot { background: var(--ok); }
.timeline li.failed .dot { background: var(--brand-red); }
.entry p { margin: 0.5rem 0 0; }
.err { color: var(--danger); }
.urgent { margin-top: 0.6rem; padding: 0.6rem 0.8rem; border-radius: var(--radius-s); background: var(--danger-soft); }
.urgent > p { display: flex; align-items: center; gap: 0.35rem; color: var(--danger); margin: 0; }
.urgent ul { margin: 0.35rem 0 0; padding-left: 1.2rem; display: grid; gap: 0.25rem; }
.urgent li span { display: block; }
.tech { margin-top: 0.6rem; }
.tech summary { cursor: pointer; color: var(--muted); }
@media (max-width: 900px) {
  .status { grid-template-columns: 1fr; }
  .status-item { border-right: 0; border-bottom: 1px solid var(--line); }
  .status-item:last-child { border-bottom: 0; }
}
</style>
