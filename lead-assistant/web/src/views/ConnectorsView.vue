<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, ApiError, formatDate } from '../api'
import { can } from '../session'

interface Connector {
  name: string
  title: string
  kind: string
  fields: string[]
  contract: string
  config: Record<string, string | null>
  state: 'not_configured' | 'configured' | 'ok' | 'error'
  checked_at: string | null
  detail: string | null
  test_service: boolean
  removable: boolean
}

const items = ref<Connector[]>([])
const loading = ref(true)
const error = ref('')
const messages = ref<Record<string, { kind: 'ok' | 'error'; text: string }>>({})
const editing = ref<string | null>(null)
const form = ref<Record<string, string | boolean>>({})
const STATE: Record<string, string> = {
  not_configured: 'не настроено',
  configured: 'настроено, не проверено',
  ok: 'работает',
  error: 'ошибка',
}
const FIELD: Record<string, string> = {
  host: 'Сервер', port: 'Порт', user: 'Логин', password: 'Пароль', folder: 'Папка',
  bot_token: 'Токен бота', api_base: 'Адрес Bot API (для тестового сервиса)', base_url: 'Базовый адрес',
  api_key: 'Ключ API', health_path: 'Путь проверки', lead_path: 'Путь заявки', status_path: 'Путь статуса',
  quote_path: 'Путь расчёта',
  smtp_host: 'SMTP-сервер для ответов (пусто — из IMAP: imap.* → smtp.*)', smtp_port: 'SMTP-порт (по умолчанию 465)',
}

async function load() {
  loading.value = true
  try {
    items.value = (await api.get<{ connectors: Connector[] }>('/api/connectors')).connectors
    error.value = ''
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось загрузить подключения'
  } finally {
    loading.value = false
  }
}

function edit(c: Connector) {
  editing.value = c.name
  form.value = { ...Object.fromEntries(c.fields.map((f) => [f, c.config[f] ?? ''])), test_service: c.test_service }
}

async function save(c: Connector) {
  try {
    await api.put(`/api/connectors/${c.name}`, form.value)
    editing.value = null
    messages.value[c.name] = { kind: 'ok', text: 'Параметры сохранены. Нажмите «Проверить».' }
    await load()
  } catch (e) {
    messages.value[c.name] = { kind: 'error', text: e instanceof ApiError ? e.message : 'Не сохранено' }
  }
}

async function check(c: Connector) {
  try {
    const res = await api.post<Connector>(`/api/connectors/${c.name}/check`)
    messages.value[c.name] = { kind: res.state === 'ok' ? 'ok' : 'error', text: res.detail ?? '' }
    await load()
  } catch (e) {
    messages.value[c.name] = { kind: 'error', text: e instanceof ApiError ? e.message : 'Проверка не выполнена' }
  }
}

async function importNow(c: Connector) {
  try {
    const res = await api.post<{ imported: number; skipped: number; ids: Array<string | number> }>(`/api/connectors/${c.name}/import`)
    const text = res.imported
      ? `Импортировано писем: ${res.imported} (№ ${res.ids.join(', ')}). Агент разберёт их автоматически — см. «Почта».`
      : res.skipped
        ? `Новых писем нет: все ${res.skipped} уже были импортированы раньше и лежат в «Почте».`
        : 'В ящике нет писем.'
    messages.value[c.name] = { kind: 'ok', text }
  } catch (e) {
    messages.value[c.name] = { kind: 'error', text: e instanceof ApiError ? e.message : 'Импорт не выполнен' }
  }
}

async function addMailbox() {
  try {
    const created = await api.post<Connector>('/api/connectors')
    await load()
    edit(items.value.find((c) => c.name === created.name) ?? created)
    messages.value[created.name] = { kind: 'ok', text: 'Новый ящик: заполните параметры, сохраните и нажмите «Проверить».' }
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось добавить ящик'
  }
}

async function remove(c: Connector) {
  if (!window.confirm(`Удалить подключение «${c.title}»? Уже импортированные письма останутся.`)) return
  try {
    await api.del(`/api/connectors/${c.name}`)
    await load()
  } catch (e) {
    messages.value[c.name] = { kind: 'error', text: e instanceof ApiError ? e.message : 'Не удалось удалить' }
  }
}

onMounted(load)
</script>

<template>
  <main class="page">
    <div class="row" style="justify-content: space-between">
      <h1>Подключения</h1>
      <button v-if="can('admin')" class="primary" @click="addMailbox">+ Добавить почтовый ящик</button>
    </div>
    <p class="muted small">
      Внешние системы включаются после ввода параметров и успешной проверки. Подключённые ящики и Telegram
      проверяются автоматически раз в минуту, новые письма сразу разбирает агент. Ответ клиенту уходит с того
      ящика, в который пришло письмо, — только по кнопке «Отправить ответ» в письме.
    </p>
    <div v-if="loading" class="empty"><span class="spinner"></span> Загрузка…</div>
    <div v-else-if="error" class="alert error">{{ error }} <button @click="load">Повторить</button></div>
    <div v-else class="grid">
      <section v-for="c in items" :key="c.name" class="card">
        <div class="row">
          <h2 style="margin: 0">{{ c.title }}</h2>
          <span class="grow"></span>
          <span class="badge" :class="{ low: c.state === 'ok', high: c.state === 'error', gray: c.state === 'not_configured', medium: c.state === 'configured' }">
            {{ STATE[c.state] }}
          </span>
        </div>
        <p v-if="c.test_service" class="badge medium">тестовый сервис</p>
        <p class="small muted">{{ c.contract }}</p>
        <div v-if="c.detail" class="small">Последняя проверка {{ formatDate(c.checked_at) }}: {{ c.detail }}</div>
        <div v-if="messages[c.name]" class="alert small" :class="messages[c.name].kind">{{ messages[c.name].text }}</div>

        <form v-if="editing === c.name" @submit.prevent="save(c)">
          <div v-for="f in c.fields" :key="f">
            <label :for="c.name + f">{{ FIELD[f] ?? f }}</label>
            <input :id="c.name + f" v-model="form[f] as string" :type="['password', 'bot_token', 'api_key'].includes(f) ? 'password' : 'text'" autocomplete="off" />
          </div>
          <label class="row" style="color: var(--text)"><input v-model="form.test_service" type="checkbox" style="width: auto; min-height: 0" /> Это тестовый сервис</label>
          <div class="row" style="margin-top: 8px">
            <button class="primary" type="submit">Сохранить</button>
            <button type="button" @click="editing = null">Отмена</button>
          </div>
        </form>
        <div v-else class="row" style="margin-top: 8px">
          <button v-if="can('admin')" @click="edit(c)">Параметры</button>
          <button v-if="can('admin')" :disabled="c.state === 'not_configured'" @click="check(c)">Проверить</button>
          <button v-if="can('supervisor') && (c.kind === 'imap' || c.kind === 'telegram')" :disabled="c.state !== 'ok'" @click="importNow(c)">
            Проверить почту сейчас
          </button>
          <button v-if="can('admin') && c.removable" class="danger" @click="remove(c)">Удалить</button>
        </div>
      </section>
    </div>
  </main>
</template>

<style scoped>
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 12px; }
</style>
