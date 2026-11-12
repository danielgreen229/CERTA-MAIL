<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, ApiError } from '../api'

interface Metrics {
  decided: number
  processed_leads: number
  awaiting_decision: number
  accepted_without_edits: number
  corrected: number
  rejected: number
  accepted_share: number | null
  category_corrections: Array<{ change: string; count: number }>
  priority_corrections: Array<{ change: string; count: number }>
  edited_fields: Record<string, number>
  rejection_reasons: Array<{ reason: string; count: number }>
  repeated_errors: Array<{ error: string; count: number }>
}

const data = ref<Metrics | null>(null)
const loading = ref(true)
const error = ref('')
const FIELD: Record<string, string> = { category: 'категория', priority: 'приоритет', draft_reply: 'черновик' }

async function load() {
  loading.value = true
  try {
    data.value = await api.get<Metrics>('/api/quality')
    error.value = ''
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось загрузить показатели'
  } finally {
    loading.value = false
  }
}
onMounted(load)
</script>

<template>
  <main class="page">
    <div class="row" style="justify-content: space-between">
      <h1>Качество агента</h1>
      <a href="/api/quality/cases" download><button>Выгрузить исправления в набор проверок</button></a>
    </div>
    <div v-if="loading" class="empty"><span class="spinner"></span> Загрузка…</div>
    <div v-else-if="error" class="alert error">{{ error }} <button @click="load">Повторить</button></div>
    <template v-else-if="data">
      <div v-if="!data.decided" class="empty">Решений менеджеров пока нет — показатели появятся после первых решений.</div>
      <div class="tiles">
        <div class="card"><div class="muted small">Принято без правок</div><div class="big">{{ data.accepted_share === null ? '—' : Math.round(data.accepted_share * 100) + '%' }}</div><div class="small muted">{{ data.accepted_without_edits }} из {{ data.decided }}</div></div>
        <div class="card"><div class="muted small">Исправлено</div><div class="big">{{ data.corrected }}</div></div>
        <div class="card"><div class="muted small">Отклонено</div><div class="big">{{ data.rejected }}</div></div>
        <div class="card"><div class="muted small">Ждут решения</div><div class="big">{{ data.awaiting_decision }}</div><div class="small muted">из {{ data.processed_leads }} обработанных</div></div>
      </div>
      <div class="grid">
        <section class="card">
          <h2>Исправления категорий</h2>
          <div v-if="!data.category_corrections.length" class="muted small">Нет</div>
          <table v-else><tbody><tr v-for="c in data.category_corrections" :key="c.change"><td>{{ c.change }}</td><td>{{ c.count }}</td></tr></tbody></table>
        </section>
        <section class="card">
          <h2>Исправления приоритетов</h2>
          <div v-if="!data.priority_corrections.length" class="muted small">Нет</div>
          <table v-else><tbody><tr v-for="c in data.priority_corrections" :key="c.change"><td>{{ c.change }}</td><td>{{ c.count }}</td></tr></tbody></table>
        </section>
        <section class="card">
          <h2>Причины отклонений</h2>
          <div v-if="!data.rejection_reasons.length" class="muted small">Нет</div>
          <table v-else><tbody><tr v-for="r in data.rejection_reasons" :key="r.reason"><td>{{ r.reason }}</td><td>{{ r.count }}</td></tr></tbody></table>
        </section>
        <section class="card">
          <h2>Повторяющиеся ошибки</h2>
          <div v-if="!data.repeated_errors.length" class="muted small">Повторов нет</div>
          <table v-else><tbody><tr v-for="r in data.repeated_errors" :key="r.error"><td>{{ r.error }}</td><td>{{ r.count }}</td></tr></tbody></table>
          <div v-if="Object.keys(data.edited_fields).length" class="small muted" style="margin-top: 6px">
            Правили поля: <span v-for="(n, f) in data.edited_fields" :key="f">{{ FIELD[f] ?? f }} — {{ n }}; </span>
          </div>
        </section>
      </div>
    </template>
  </main>
</template>

<style scoped>
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; margin-bottom: 12px; }
.big { font-size: 28px; font-weight: 700; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 10px; }
</style>
