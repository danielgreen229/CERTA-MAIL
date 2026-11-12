<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, ApiError, formatDate, ROLE, type User } from '../api'
import Icon from '../components/Icon.vue'
import UiSelect from '../components/UiSelect.vue'
import { soundOn, toggleSound } from '../notify'
import { startTour } from '../onboarding'
import { can, loadSession, session } from '../session'
import { theme, THEME_TITLE, type ThemeMode } from '../theme'

/**
 * Настройки по роли: менеджер — только своё (пароль, тема, звук);
 * руководитель — ещё сроки реакции (просмотр) и журнал; администратор — всё.
 */
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
const PRIORITY_TITLE: Record<string, string> = { high: 'Высокая срочность', medium: 'Средняя', low: 'Низкая' }
const CATEGORY_TITLE: Record<string, string> = { sale: 'Продажи', complaint: 'Жалобы', question: 'Вопросы' }
const ROLE_OPTIONS = Object.entries(ROLE).map(([value, label]) => ({ value, label }))
const THEME_OPTIONS = (['system', 'light', 'dark'] as ThemeMode[]).map((value) => ({
  value,
  label: THEME_TITLE[value].replace('Тема: ', ''),
}))

/** Журнал — человеческими словами вместо кодов событий. */
const ACTIONS: Record<string, string> = {
  login: 'Вход', login_failed: 'Неудачный вход', logout: 'Выход', password_changed: 'Смена пароля',
  user_created: 'Создан пользователь', decision: 'Решение по письму', assigned: 'Назначен ответственный',
  reply_sent: 'Ответ отправлен', reply_failed: 'Ответ не отправлен', job_created: 'Запущен разбор',
  connector_configured: 'Изменено подключение', connector_checked: 'Проверено подключение',
  connector_added: 'Добавлен ящик', connector_removed: 'Удалён ящик', messages_imported: 'Получены письма',
  settings_changed: 'Изменены настройки', kb_uploaded: 'Загружен документ', kb_deleted: 'Удалён документ',
}

async function load() {
  try {
    if (can('supervisor')) {
      settings.value = await api.get<Settings>('/api/settings')
      audit.value = (await api.get<{ events: typeof audit.value }>('/api/audit')).events.slice(0, 50)
    }
    if (can('admin')) users.value = (await api.get<{ users: User[] }>('/api/users')).users
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
    userMessage.value = { kind: 'ok', text: 'Сотрудник добавлен. При первом входе он сменит пароль.' }
    userForm.value = { login: '', name: '', role: 'manager', password: '' }
    await load()
  } catch (e) {
    userMessage.value = { kind: 'error', text: e instanceof ApiError ? e.message : 'Не удалось добавить сотрудника' }
  }
}

const workDays = computed(() => settings.value?.work_hours.days.map((d) => DAYS[d]).join(', ') ?? '')
const initials = computed(() =>
  (session.user?.name ?? '?').split(/\s+/).map((w) => w[0]).slice(0, 2).join('').toUpperCase(),
)

onMounted(load)
</script>

<template>
  <div class="page settings">
    <div class="page-head">
      <h1><Icon name="settings" /> Настройки</h1>
    </div>
    <div v-if="error" class="alert error"><Icon name="info" /> {{ error }}</div>
    <div v-if="message" class="alert ok"><Icon name="check" /> {{ message }}</div>

    <!-- Для всех: свой профиль и вид интерфейса. -->
    <section class="card profile">
      <span class="avatar" aria-hidden="true">{{ initials }}</span>
      <div class="grow">
        <h2>{{ session.user?.name }}</h2>
        <p class="muted small">{{ session.user ? ROLE[session.user.role] : '' }} · вход: {{ session.user?.login }}</p>
      </div>
      <RouterLink to="/password" class="btn-link"><Icon name="key" /> Сменить пароль</RouterLink>
    </section>

    <section class="card">
      <h2>Вид и уведомления</h2>
      <div class="prefs">
        <div>
          <label>Тема оформления</label>
          <UiSelect v-model="theme" :options="THEME_OPTIONS" aria-label="Тема оформления" />
        </div>
        <div>
          <label>Обучение</label>
          <button type="button" @click="startTour"><Icon name="run" /> Пройти обучение заново</button>
        </div>
        <div>
          <label>Звук о новых письмах</label>
          <button type="button" :aria-pressed="soundOn" @click="toggleSound">
            <Icon :name="soundOn ? 'bell' : 'bellOff'" /> {{ soundOn ? 'Включён' : 'Выключен' }}
          </button>
        </div>
      </div>
    </section>

    <!-- Руководитель: сроки — просмотр; администратор — правка. -->
    <section v-if="settings && can('supervisor')" class="card">
      <h2>
        Рабочее время и сроки ответа
        <span v-if="settings.demo" class="badge medium">примерные — настройте</span>
      </h2>
      <template v-if="can('admin')">
        <div class="grid">
          <div><label for="tz">Часовой пояс</label><input id="tz" v-model="settings.timezone" placeholder="Europe/Moscow" /></div>
          <div><label for="ws">Рабочий день с (час)</label><input id="ws" v-model.number="settings.work_hours.start" type="number" min="0" max="23" /></div>
          <div><label for="we">до (час)</label><input id="we" v-model.number="settings.work_hours.end" type="number" min="1" max="24" /></div>
        </div>
        <label>Рабочие дни</label>
        <div class="days">
          <button
            v-for="(d, i) in DAYS"
            :key="d"
            type="button"
            :class="{ primary: settings.work_hours.days.includes(i) }"
            :aria-pressed="settings.work_hours.days.includes(i)"
            @click="toggleDay(i)"
          >{{ d }}</button>
        </div>
        <div class="grid">
          <div v-for="p in ['high', 'medium', 'low']" :key="p">
            <label :for="'sla' + p">{{ PRIORITY_TITLE[p] }}: ответить за, рабочих часов</label>
            <input :id="'sla' + p" v-model.number="settings.sla_hours[p]" type="number" min="0.5" step="0.5" />
          </div>
        </div>
        <h3>Кому достаются письма по умолчанию</h3>
        <div class="grid">
          <div v-for="c in ['sale', 'complaint', 'question']" :key="c">
            <label :for="'as' + c">{{ CATEGORY_TITLE[c] }}</label>
            <input :id="'as' + c" v-model="settings.assignment[c]" placeholder="Название отдела" />
          </div>
        </div>
        <details class="advanced">
          <summary><Icon name="agent" /> Модель помощника (для администратора)</summary>
          <div class="grid">
            <div><label for="mm">Модель (пусто — по умолчанию)</label><input id="mm" v-model="settings.model.model" placeholder="qwen3-8b" /></div>
            <div><label for="mb">Сборка llama.cpp</label><input id="mb" v-model="settings.model.build" placeholder="cpu / vulkan / cuda" /></div>
            <div><label for="mu">Адрес сервера модели</label><input id="mu" v-model="settings.model.llm_url" placeholder="http://llm:8080/v1" /></div>
          </div>
        </details>
        <button class="primary save" @click="save"><Icon name="check" /> Сохранить</button>
      </template>
      <dl v-else class="facts">
        <dt>Рабочее время</dt><dd>{{ workDays }}, {{ settings.work_hours.start }}:00–{{ settings.work_hours.end }}:00 ({{ settings.timezone }})</dd>
        <template v-for="p in ['high', 'medium', 'low']" :key="p">
          <dt>{{ PRIORITY_TITLE[p] }}</dt>
          <dd>ответить за {{ settings.sla_hours[p] }} раб. ч</dd>
        </template>
      </dl>
    </section>

    <section v-if="can('admin')" class="card">
      <h2>Сотрудники</h2>
      <table>
        <thead><tr><th>Имя</th><th>Логин</th><th>Роль</th></tr></thead>
        <tbody><tr v-for="u in users" :key="u.id"><td>{{ u.name }}</td><td>{{ u.login }}</td><td>{{ ROLE[u.role] }}</td></tr></tbody>
      </table>
      <h3><Icon name="assign" /> Добавить сотрудника</h3>
      <form class="grid add-user" @submit.prevent="addUser">
        <div><label for="un">Имя и фамилия</label><input id="un" v-model="userForm.name" required /></div>
        <div><label for="ul">Логин для входа</label><input id="ul" v-model="userForm.login" required autocomplete="off" /></div>
        <div><label>Роль</label><UiSelect v-model="userForm.role" :options="ROLE_OPTIONS" aria-label="Роль" /></div>
        <div><label for="up">Начальный пароль (от 10 символов)</label><input id="up" v-model="userForm.password" type="password" required minlength="10" autocomplete="new-password" /></div>
        <div class="end"><button class="primary" type="submit"><Icon name="plus" /> Добавить</button></div>
      </form>
      <div v-if="userMessage" class="alert" :class="userMessage.kind">{{ userMessage.text }}</div>
    </section>

    <section v-if="can('supervisor')" class="card">
      <h2>Журнал действий</h2>
      <div class="table-wrap">
        <table class="small">
          <thead><tr><th>Когда</th><th>Кто</th><th>Что сделано</th></tr></thead>
          <tbody>
            <tr v-for="(e, i) in audit" :key="i">
              <td class="num">{{ formatDate(e.ts) }}</td>
              <td>{{ e.user ?? 'Система' }}</td>
              <td>{{ ACTIONS[e.action] ?? e.action }}<span v-if="e.target" class="muted"> — {{ e.target.replace(/^lead:/, 'письмо № ').replace(/^connector:/, '') }}</span></td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
    <p class="small muted">Версия {{ session.version }}</p>
  </div>
</template>

<style scoped>
.settings .card { margin-bottom: 1rem; max-width: 72rem; }
.profile { display: flex; align-items: center; gap: 1rem; flex-wrap: wrap; }
.profile h2 { margin: 0; }
.profile p { margin: 0.15rem 0 0; }
.avatar {
  width: 3rem; height: 3rem; border-radius: 50%; display: grid; place-items: center;
  background: var(--brand-navy); color: #fff; font-weight: 650;
}
.btn-link {
  display: inline-flex; align-items: center; gap: 0.45rem; padding: 0.45rem 0.85rem; border-radius: var(--radius-s);
  border: 1px solid var(--line-strong); color: var(--text); text-decoration: none; font-weight: 520;
}
.btn-link:hover { border-color: var(--accent); }
.prefs { display: grid; grid-template-columns: repeat(auto-fit, minmax(14rem, 18rem)); gap: 0.25rem 1.25rem; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr)); gap: 0 1rem; }
.days { display: flex; gap: 0.35rem; flex-wrap: wrap; }
.days button { min-width: 3rem; }
.advanced { margin-top: 1.1rem; }
.advanced summary { cursor: pointer; display: flex; align-items: center; gap: 0.45rem; color: var(--muted); font-weight: 560; }
.save { margin-top: 1.1rem; }
.facts { display: grid; grid-template-columns: max-content 1fr; gap: 0.35rem 1.25rem; margin: 0; }
.facts dt { color: var(--muted); }
.facts dd { margin: 0; }
.end { align-self: end; }
.table-wrap { overflow-x: auto; }
</style>
