<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, ApiError, formatDate, ROLE, type User } from '../api'
import { can, loadSession, session } from '../session'

interface Settings {
  demo: boolean
  timezone: string
  work_hours: { start: number; end: number; days: number[] }
  sla_hours: Record<string, number>
  assignment: Record<string, string | null>
  model: { backend?: string; model?: string; build?: string; llm_url?: string }
}

const settings = ref<Settings | null>(null)
const users = ref<User[]>([])
const audit = ref<Array<{ ts: string; user: string | null; action: string; target: string | null }>>([])
const error = ref('')
const message = ref('')
const userForm = ref({ login: '', name: '', role: 'manager', password: '' })
const userMessage = ref<{ kind: string; text: string } | null>(null)
const DAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']

async function load() {
  try {
    settings.value = await api.get<Settings>('/api/settings')
    if (can('admin')) users.value = (await api.get<{ users: User[] }>('/api/users')).users
    if (can('supervisor')) audit.value = (await api.get<{ events: typeof audit.value }>('/api/audit')).events.slice(0, 50)
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось загрузить настройки'
  }
}

async function save() {
  if (!settings.value) return
  message.value = ''
  error.value = ''
  try {
    const { timezone, work_hours, sla_hours, assignment, model } = settings.value
    settings.value = await api.put<Settings>('/api/settings', { timezone, work_hours, sla_hours, assignment, model })
    message.value = 'Настройки сохранены'
    await loadSession()
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не сохранено'
  }
}

function toggleDay(day: number) {
  const days = settings.value!.work_hours.days
  const i = days.indexOf(day)
  if (i >= 0) days.splice(i, 1)
  else days.push(day)
  days.sort()
}

async function addUser() {
  userMessage.value = null
  try {
    await api.post('/api/users', userForm.value)
    userMessage.value = { kind: 'ok', text: 'Пользователь создан; при первом входе он сменит пароль.' }
    userForm.value = { login: '', name: '', role: 'manager', password: '' }
    await load()
  } catch (e) {
    userMessage.value = { kind: 'error', text: e instanceof ApiError ? e.message : 'Не создан' }
  }
}

onMounted(load)
</script>

<template>
  <main class="page">
    <h1>Настройки</h1>
    <div class="row"><RouterLink to="/password">Сменить свой пароль</RouterLink></div>
    <div v-if="error" class="alert error">{{ error }}</div>
    <div v-if="message" class="alert ok">{{ message }}</div>
    <section v-if="settings" class="card" style="margin-top: 10px">
      <h2>Сроки реакции и назначение <span v-if="settings.demo" class="badge medium">демонстрационные</span></h2>
      <fieldset :disabled="!can('admin')">
        <div class="grid">
          <div><label for="tz">Часовой пояс</label><input id="tz" v-model="settings.timezone" /></div>
          <div><label for="ws">Рабочий день с, ч</label><input id="ws" v-model.number="settings.work_hours.start" type="number" min="0" max="23" /></div>
          <div><label for="we">по, ч</label><input id="we" v-model.number="settings.work_hours.end" type="number" min="1" max="24" /></div>
        </div>
        <label>Рабочие дни</label>
        <div class="row">
          <button v-for="(d, i) in DAYS" :key="d" type="button" :class="{ primary: settings.work_hours.days.includes(i) }" @click="toggleDay(i)">{{ d }}</button>
        </div>
        <div class="grid">
          <div v-for="p in ['high', 'medium', 'low']" :key="p">
            <label :for="'sla' + p">Срок реакции «{{ { high: 'высокий', medium: 'средний', low: 'низкий' }[p] }}», рабочих часов</label>
            <input :id="'sla' + p" v-model.number="settings.sla_hours[p]" type="number" min="0.5" step="0.5" />
          </div>
        </div>
        <div class="grid">
          <div v-for="c in ['sale', 'complaint', 'question']" :key="c">
            <label :for="'as' + c">Ответственный: {{ { sale: 'продажа', complaint: 'жалоба', question: 'вопрос' }[c] }}</label>
            <input :id="'as' + c" v-model="settings.assignment[c]" />
          </div>
        </div>
        <h3>Модель</h3>
        <div class="grid">
          <div><label for="mm">Модель (пусто — по умолчанию)</label><input id="mm" v-model="settings.model.model" placeholder="qwen3-8b" /></div>
          <div><label for="mb">Сборка llama.cpp</label><input id="mb" v-model="settings.model.build" placeholder="cpu / vulkan / cuda" /></div>
          <div><label for="mu">Адрес OpenAI-совместимого сервера (необязательно)</label><input id="mu" v-model="settings.model.llm_url" placeholder="http://llm:8080/v1" /></div>
        </div>
        <button v-if="can('admin')" class="primary" style="margin-top: 12px" @click="save">Сохранить</button>
      </fieldset>
    </section>

    <section v-if="can('admin')" class="card" style="margin-top: 12px">
      <h2>Пользователи</h2>
      <table>
        <thead><tr><th>Логин</th><th>Имя</th><th>Роль</th></tr></thead>
        <tbody><tr v-for="u in users" :key="u.id"><td>{{ u.login }}</td><td>{{ u.name }}</td><td>{{ ROLE[u.role] }}</td></tr></tbody>
      </table>
      <form class="grid" style="margin-top: 10px" @submit.prevent="addUser">
        <div><label for="ul">Логин</label><input id="ul" v-model="userForm.login" required /></div>
        <div><label for="un">Имя</label><input id="un" v-model="userForm.name" required /></div>
        <div>
          <label for="ur">Роль</label>
          <select id="ur" v-model="userForm.role"><option v-for="(t, k) in ROLE" :key="k" :value="k">{{ t }}</option></select>
        </div>
        <div><label for="up">Начальный пароль</label><input id="up" v-model="userForm.password" type="password" required minlength="10" autocomplete="new-password" /></div>
        <div style="align-self: end"><button class="primary" type="submit">Создать</button></div>
      </form>
      <div v-if="userMessage" class="alert" :class="userMessage.kind">{{ userMessage.text }}</div>
    </section>

    <section v-if="can('supervisor')" class="card" style="margin-top: 12px">
      <h2>Журнал действий</h2>
      <div class="table-wrap">
        <table class="small">
          <thead><tr><th>Время</th><th>Кто</th><th>Действие</th><th>Объект</th></tr></thead>
          <tbody><tr v-for="(e, i) in audit" :key="i"><td>{{ formatDate(e.ts) }}</td><td>{{ e.user ?? 'система' }}</td><td>{{ e.action }}</td><td>{{ e.target }}</td></tr></tbody>
        </table>
      </div>
    </section>
    <p class="small muted">Версия {{ session.version }}</p>
  </main>
</template>

<style scoped>
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 0 12px; }
fieldset { border: 0; padding: 0; margin: 0; }
.table-wrap { overflow-x: auto; }
</style>
