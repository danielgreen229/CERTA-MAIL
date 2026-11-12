<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { api, ApiError, formatDate, type Job } from '../api'

const jobs = ref<Job[]>([])
const loading = ref(true)
const error = ref('')
const actionError = ref('')
let timer: number | undefined

const STATE: Record<string, string> = {
  queued: 'в очереди',
  running: 'выполняется',
  done: 'завершена',
  failed: 'ошибка',
  cancelled: 'отменена',
}

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    jobs.value = (await api.get<{ jobs: Job[] }>('/api/jobs')).jobs
    error.value = ''
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось загрузить задачи'
  } finally {
    loading.value = false
  }
}

async function start() {
  actionError.value = ''
  try {
    await api.post('/api/jobs', {})
    await load(true)
  } catch (e) {
    actionError.value = e instanceof ApiError ? e.message : 'Не удалось запустить'
  }
}

async function cancel(job: Job) {
  actionError.value = ''
  try {
    await api.post(`/api/jobs/${job.id}/cancel`)
    await load(true)
  } catch (e) {
    actionError.value = e instanceof ApiError ? e.message : 'Не удалось отменить'
  }
}

const active = () => jobs.value.some((j) => j.state === 'queued' || j.state === 'running')

onMounted(() => {
  load()
  timer = window.setInterval(() => load(true), 4000)
})
onUnmounted(() => window.clearInterval(timer))
</script>

<template>
  <main class="page">
    <div class="row" style="justify-content: space-between">
      <h1>Фоновая обработка</h1>
      <button class="primary" :disabled="active()" @click="start">
        {{ active() ? 'Обработка идёт…' : 'Обработать новые / повторить ошибочные' }}
      </button>
    </div>
    <p class="muted small">
      Задача выполняется отдельным обработчиком: страницу можно закрыть. После перезапуска обработчик
      продолжит незавершённую задачу; уже записанные заявки повторно не обрабатываются.
    </p>
    <div v-if="actionError" class="alert error">{{ actionError }}</div>
    <div v-if="loading" class="empty"><span class="spinner"></span> Загрузка…</div>
    <div v-else-if="error" class="alert error">{{ error }} <button @click="load()">Повторить</button></div>
    <div v-else-if="!jobs.length" class="empty">Задач ещё не было.</div>
    <div v-for="job in jobs" v-else :key="job.id" class="card job">
      <div class="row">
        <strong>{{ job.id }}</strong>
        <span class="badge" :class="{ high: job.state === 'failed', low: job.state === 'done', gray: job.state === 'cancelled' }">
          {{ STATE[job.state] }}
        </span>
        <span class="muted small">создана {{ formatDate(job.created_at) }} · попыток {{ job.attempts }}/{{ job.max_attempts }}</span>
        <span class="grow"></span>
        <button v-if="job.state === 'queued'" @click="cancel(job)">Отменить</button>
      </div>
      <div v-if="job.progress.total" class="small" style="margin-top: 6px">
        <div class="progress"><div :style="{ width: Math.round(((job.progress.done ?? 0) / job.progress.total) * 100) + '%' }"></div></div>
        записано {{ job.progress.done }} из {{ job.progress.total }}
        <span v-if="job.progress.pending_ids?.length && job.state !== 'running'" class="muted">
          · не записаны: {{ job.progress.pending_ids.join(', ') }}
        </span>
      </div>
      <div v-if="job.state === 'running' && job.progress.log?.length" class="small muted log">
        <div v-for="(line, i) in job.progress.log" :key="i">{{ line }}</div>
      </div>
      <div v-if="job.error" class="alert error small">{{ job.error.code }}: {{ job.error.message }}</div>
      <template v-if="job.summary">
        <div v-if="job.summary.urgent?.length" class="small" style="margin-top: 8px">
          <b>Срочные:</b>
          <ul>
            <li v-for="u in job.summary.urgent" :key="String(u.id)">№ {{ u.id }} — {{ u.basis }}<span v-if="u.next">. {{ u.next }}</span></li>
          </ul>
        </div>
        <details>
          <summary class="small">Сводка для руководителя{{ job.summary.model ? ` · модель ${job.summary.model}` : '' }}</summary>
          <pre class="small">{{ job.summary.text }}</pre>
        </details>
      </template>
    </div>
  </main>
</template>

<style scoped>
.job { margin-bottom: 10px; }
.log { margin-top: 6px; max-height: 140px; overflow: auto; }
ul { margin: 4px 0; padding-left: 18px; }
</style>
