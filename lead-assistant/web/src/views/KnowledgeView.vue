<script setup lang="ts">
import UiSelect from '../components/UiSelect.vue'
import Icon from '../components/Icon.vue'
import { onMounted, ref } from 'vue'
import { api, ApiError, formatDate, ROLE, type KbHit } from '../api'
import { can } from '../session'

interface Doc {
  id: number
  title: string
  version: string
  valid_from: string | null
  valid_to: string | null
  owner: string
  filename: string
  size_bytes: number
  status: 'indexed' | 'needs_ocr' | 'empty'
  min_role: 'manager' | 'supervisor' | 'admin'
  current: boolean
  conflict: boolean
  created_at: string
}

const docs = ref<Doc[]>([])
const limits = ref<{ max_bytes: number; types: string[] }>({ max_bytes: 0, types: [] })
const loading = ref(true)
const error = ref('')
const uploadError = ref('')
const uploadOk = ref('')
const busy = ref(false)
const form = ref({ title: '', version: '1', owner: '', valid_from: '', valid_to: '', min_role: 'manager' })
const file = ref<File | null>(null)
const query = ref('')
const hits = ref<KbHit[] | null>(null)
const conflicts = ref<string[]>([])
const STATUS: Record<string, string> = { indexed: 'в поиске', needs_ocr: 'скан: нужен OCR', empty: 'пустой' }

async function load() {
  loading.value = true
  try {
    const data = await api.get<{ documents: Doc[]; limits: { max_bytes: number; types: string[] } }>('/api/kb/documents')
    docs.value = data.documents
    limits.value = data.limits
    error.value = ''
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось загрузить документы'
  } finally {
    loading.value = false
  }
}

async function upload() {
  uploadError.value = ''
  uploadOk.value = ''
  if (!file.value) {
    uploadError.value = 'Выберите файл'
    return
  }
  busy.value = true
  const data = new FormData()
  data.append('file', file.value)
  Object.entries(form.value).forEach(([k, v]) => data.append(k, v))
  try {
    const res = await api.post<{ document: Doc }>('/api/kb/documents', data)
    uploadOk.value = res.document.status === 'needs_ocr'
      ? 'Загружено, но это скан без текста: нужен OCR, в поиск не попадёт.'
      : 'Документ загружен и проиндексирован.'
    await load()
  } catch (e) {
    uploadError.value = e instanceof ApiError ? e.message : 'Не удалось загрузить'
  } finally {
    busy.value = false
  }
}

async function remove(doc: Doc) {
  if (!confirm(`Удалить документ «${doc.title}» (версия ${doc.version})?`)) return
  try {
    await api.del(`/api/kb/documents/${doc.id}`)
    await load()
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось удалить'
  }
}

async function search() {
  if (!query.value.trim()) return
  try {
    const res = await api.get<{ results: KbHit[]; conflicts: string[] }>(`/api/kb/search?q=${encodeURIComponent(query.value)}`)
    hits.value = res.results
    conflicts.value = res.conflicts
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Поиск не выполнен'
  }
}

onMounted(load)
const ROLE_OPTIONS = Object.entries(ROLE).map(([value, label]) => ({ value, label: `${label} и выше` }))
</script>

<template>
  <div class="page">
    <div class="page-head"><h1><Icon name="book" /> База знаний</h1></div>
    <p class="muted small">
      Документы компании (тарифы, регламенты, условия). Фрагменты действующих документов показываются в карточке заявки
      как источники для ответа. Типы: {{ limits.types.join(', ') }}, до {{ Math.round(limits.max_bytes / 1048576) }} МБ.
    </p>

    <section class="card">
      <h2>Поиск</h2>
      <form class="row" @submit.prevent="search">
        <input v-model="query" class="grow" placeholder="Например: отсрочка платежа юрлица" style="flex: 1; width: auto" />
        <button class="primary" type="submit">Найти</button>
      </form>
      <div v-for="c in conflicts" :key="c" class="alert warn small">{{ c }}</div>
      <div v-if="hits && !hits.length" class="muted small" style="margin-top: 8px">Ничего не найдено в действующих документах.</div>
      <div v-for="h in hits ?? []" :key="h.chunk_id" class="hit">
        <div class="quote small">{{ h.fragment }}</div>
        <div class="small muted">{{ h.source }} · ответственный {{ h.document.owner }}</div>
      </div>
    </section>

    <section v-if="can('supervisor')" class="card" style="margin-top: 12px">
      <h2>Загрузить документ</h2>
      <form class="upload" @submit.prevent="upload">
        <div><label for="f">Файл</label><input id="f" type="file" accept=".txt,.md,.pdf" @change="file = ($event.target as HTMLInputElement).files?.[0] ?? null" /></div>
        <div><label for="t">Название</label><input id="t" v-model="form.title" required /></div>
        <div><label for="v">Версия</label><input id="v" v-model="form.version" required /></div>
        <div><label for="o">Ответственный</label><input id="o" v-model="form.owner" required /></div>
        <div><label for="vf">Действует с</label><input id="vf" v-model="form.valid_from" type="date" /></div>
        <div><label for="vt">Действует по</label><input id="vt" v-model="form.valid_to" type="date" /></div>
        <div>
          <label for="r">Доступ</label>
          <UiSelect id="r" v-model="form.min_role" :options="ROLE_OPTIONS" aria-label="Кто видит документ" />
        </div>
        <div style="align-self: end"><button class="primary" type="submit" :disabled="busy">Загрузить</button></div>
      </form>
      <div v-if="uploadError" class="alert error">{{ uploadError }}</div>
      <div v-if="uploadOk" class="alert ok">{{ uploadOk }}</div>
    </section>

    <section class="card" style="margin-top: 12px">
      <h2>Документы</h2>
      <div v-if="loading" class="empty"><span class="spinner"></span> Загрузка…</div>
      <div v-else-if="error" class="alert error">{{ error }}</div>
      <div v-else-if="!docs.length" class="empty">Документов пока нет.</div>
      <div v-else class="table-wrap">
        <table>
          <thead><tr><th>Название</th><th>Версия</th><th>Действует</th><th>Ответственный</th><th>Состояние</th><th class="hide-mobile">Загружен</th><th></th></tr></thead>
          <tbody>
            <tr v-for="d in docs" :key="d.id">
              <td>{{ d.title }}<div class="small muted">{{ d.filename }}</div></td>
              <td>{{ d.version }}</td>
              <td class="small">{{ d.valid_from || '…' }} — {{ d.valid_to || '…' }}<div v-if="!d.current" class="badge gray">не действует</div></td>
              <td>{{ d.owner }}</td>
              <td>
                <span class="badge" :class="{ medium: d.status !== 'indexed' }">{{ STATUS[d.status] }}</span>
                <div v-if="d.conflict" class="badge high">несколько действующих версий</div>
              </td>
              <td class="small hide-mobile">{{ formatDate(d.created_at) }}</td>
              <td><button v-if="can('supervisor')" class="danger" @click="remove(d)">Удалить</button></td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>

<style scoped>
.upload { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 0 12px; }
.hit { margin-top: 10px; }
.table-wrap { overflow-x: auto; }
</style>
