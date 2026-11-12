<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, ApiError, formatDate } from '../api'
import Icon, { type IconName } from '../components/Icon.vue'
import { loadMail } from '../mailbox'
import { can } from '../session'

/**
 * Почтовые ящики и Telegram-боты — списками: у каждого сотрудника их сколько угодно.
 * Сервисы компании (CRM, TMS, тарифы) видит и настраивает только администратор.
 */
interface Connector {
  name: string
  title: string
  kind: 'imap' | 'telegram' | 'rest'
  fields: string[]
  contract: string
  config: Record<string, string | null>
  state: 'not_configured' | 'configured' | 'ok' | 'error'
  checked_at: string | null
  detail: string | null
  test_service: boolean
  removable: boolean
  owner: { id: number; name: string } | null
}

const items = ref<Connector[]>([])
const loading = ref(true)
const error = ref('')
const messages = ref<Record<string, { kind: 'ok' | 'error'; text: string }>>({})
const editing = ref<string | null>(null)
const busy = ref<string | null>(null)
const form = ref<Record<string, string | boolean>>({})

const STATE: Record<string, { label: string; tone: string }> = {
  not_configured: { label: 'Не настроено', tone: 'gray' },
  configured: { label: 'Не проверено', tone: 'medium' },
  ok: { label: 'Работает', tone: 'low' },
  error: { label: 'Ошибка', tone: 'high' },
}
const FIELD: Record<string, { label: string; placeholder?: string; hint?: string }> = {
  host: { label: 'IMAP-сервер', placeholder: 'imap.mail.ru' },
  port: { label: 'Порт', placeholder: '993' },
  user: { label: 'Адрес почты', placeholder: 'name@mail.ru' },
  password: { label: 'Пароль для внешних приложений', hint: 'Не обычный пароль от почты — его создают в настройках безопасности ящика.' },
  folder: { label: 'Папка', placeholder: 'INBOX' },
  smtp_host: { label: 'SMTP-сервер для ответов', placeholder: 'пусто — подставится сам', hint: 'Обычно не нужен: imap.mail.ru → smtp.mail.ru.' },
  smtp_port: { label: 'SMTP-порт', placeholder: '465 (по умолчанию)' },
  bot_token: { label: 'Токен бота', placeholder: '1234567890:AA…', hint: 'Его выдаёт @BotFather после команды /newbot.' },
  api_base: { label: 'Адрес Bot API тестового сервиса', placeholder: 'http://127.0.0.1:8099' },
  base_url: { label: 'Базовый адрес' },
  api_key: { label: 'Ключ API' },
  health_path: { label: 'Путь проверки' },
  lead_path: { label: 'Путь заявки' },
  status_path: { label: 'Путь статуса' },
  quote_path: { label: 'Путь расчёта' },
}
const SECRET = ['password', 'bot_token', 'api_key']
const ADVANCED = ['smtp_host', 'smtp_port', 'api_base']
const SERVICE_ICON: Record<string, IconName> = { crm: 'decide', tms: 'truck', tariffs: 'sale' }
const SERVICE_ABOUT: Record<string, string> = {
  crm: 'Карточки клиентов и сделки. Пока доступна только проверка связи.',
  tms: 'Статус груза по номеру накладной — прямо в окне письма.',
  tariffs: 'Расчёт стоимости перевозки. Пока доступна только проверка связи.',
}

const mailboxes = computed(() => items.value.filter((c) => c.kind === 'imap'))
const bots = computed(() => items.value.filter((c) => c.kind === 'telegram'))
const services = computed(() => items.value.filter((c) => c.kind === 'rest'))
const groups = computed(() => [
  { key: 'email' as const, icon: 'mail' as IconName, title: 'Почтовые ящики', list: mailboxes.value, add: 'Добавить ящик', empty: 'Ящиков пока нет. Добавьте почту, на которую пишут клиенты.' },
  { key: 'telegram' as const, icon: 'telegram' as IconName, title: 'Telegram-боты', list: bots.value, add: 'Добавить бота', empty: 'Ботов пока нет. Создайте бота у @BotFather и добавьте его токен.' },
])

async function load() {
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

const mainFields = (c: Connector) => c.fields.filter((f) => !ADVANCED.includes(f))
const extraFields = (c: Connector) => c.fields.filter((f) => ADVANCED.includes(f) && (f !== 'api_base' || !!form.value.test_service))

function say(c: Connector, kind: 'ok' | 'error', text: string) {
  messages.value = { ...messages.value, [c.name]: { kind, text } }
}

async function save(c: Connector) {
  busy.value = c.name
  try {
    const payload = { ...form.value }
    if (!payload.test_service && 'api_base' in payload) payload.api_base = ''
    await api.put(`/api/connectors/${c.name}`, payload)
    editing.value = null
    // Сразу проверяем связь, чтобы не нажимать вторую кнопку.
    const res = await api.post<Connector>(`/api/connectors/${c.name}/check`)
    say(c, res.state === 'ok' ? 'ok' : 'error', res.state === 'ok' ? `Сохранено и работает: ${res.detail}` : res.detail ?? 'Проверка не прошла')
    await load()
  } catch (e) {
    say(c, 'error', e instanceof ApiError ? e.message : 'Не сохранено')
  } finally {
    busy.value = null
  }
}

async function check(c: Connector) {
  busy.value = c.name
  try {
    const res = await api.post<Connector>(`/api/connectors/${c.name}/check`)
    say(c, res.state === 'ok' ? 'ok' : 'error', res.detail ?? '')
    await load()
  } catch (e) {
    say(c, 'error', e instanceof ApiError ? e.message : 'Проверка не выполнена')
  } finally {
    busy.value = null
  }
}

async function importNow(c: Connector) {
  busy.value = c.name
  try {
    const res = await api.post<{ imported: number; skipped: number }>(`/api/connectors/${c.name}/import`)
    say(c, 'ok', res.imported ? `Получено новых: ${res.imported}. Помощник разберёт их автоматически.` : 'Новых сообщений нет.')
    loadMail(true)
  } catch (e) {
    say(c, 'error', e instanceof ApiError ? e.message : 'Не удалось получить сообщения')
  } finally {
    busy.value = null
  }
}

async function add(kind: 'email' | 'telegram') {
  try {
    const created = await api.post<Connector>('/api/connectors', { kind })
    await load()
    const fresh = items.value.find((c) => c.name === created.name)
    if (fresh) edit(fresh)
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось добавить'
  }
}

async function remove(c: Connector) {
  if (!window.confirm(`Удалить «${c.title}»? Уже полученные письма останутся в «Почте».`)) return
  try {
    await api.del(`/api/connectors/${c.name}`)
    await load()
  } catch (e) {
    say(c, 'error', e instanceof ApiError ? e.message : 'Не удалось удалить')
  }
}

const lastCheck = (c: Connector) => (c.checked_at ? `проверено ${formatDate(c.checked_at)}` : 'ещё не проверялось')
const iconOf = (c: Connector): IconName =>
  c.kind === 'imap' ? 'mail' : c.kind === 'telegram' ? 'telegram' : SERVICE_ICON[c.name] ?? 'plug'

onMounted(load)
</script>

<template>
  <div class="page conn">
    <div class="page-head">
      <h1><Icon name="plug" /> Почта и сервисы</h1>
      <p class="lead">
        Подключённые ящики и боты проверяются раз в минуту — новые сообщения сами попадают в «Почту»
        и разбираются помощником. Ответ клиенту уходит с того ящика или бота, куда он написал.
      </p>
    </div>
    <div v-if="loading" class="empty"><span class="spinner"></span> Загружаю…</div>
    <div v-else-if="error" class="alert error"><Icon name="info" /> {{ error }} <button class="link" @click="load">Повторить</button></div>

    <template v-else>
      <section v-for="group in groups" :key="group.key" class="card group">
        <div class="group-head">
          <h2><Icon :name="group.icon" /> {{ group.title }} <span class="count num">{{ group.list.length }}</span></h2>
          <button class="primary" @click="add(group.key)"><Icon name="plus" /> {{ group.add }}</button>
        </div>
        <p v-if="!group.list.length" class="muted empty-line">{{ group.empty }}</p>
        <ul v-else class="rows">
          <li v-for="c in group.list" :key="c.name" class="item" :class="{ open: editing === c.name }">
            <div class="row-main">
              <span class="kind" :class="c.state"><Icon :name="iconOf(c)" size="1.2rem" /></span>
              <div class="who">
                <b>{{ c.title }}</b>
                <span class="small muted">
                  {{ lastCheck(c) }}<template v-if="c.owner && can('admin')"> · владелец: {{ c.owner.name }}</template>
                </span>
              </div>
              <span class="badge" :class="STATE[c.state]?.tone">{{ STATE[c.state]?.label }}</span>
              <span v-if="c.test_service" class="badge medium">тестовый</span>
              <div class="acts">
                <button class="ghost" :disabled="c.state !== 'ok' || busy === c.name" title="Забрать новые сообщения сейчас" @click="importNow(c)">
                  <Icon name="inbox" /> <span class="hide-narrow">Забрать</span>
                </button>
                <button class="ghost icon-only" :disabled="c.state === 'not_configured' || busy === c.name" title="Проверить связь" aria-label="Проверить связь" @click="check(c)">
                  <Icon name="refresh" />
                </button>
                <button class="ghost icon-only" :aria-expanded="editing === c.name" title="Настроить" aria-label="Настроить" @click="editing === c.name ? (editing = null) : edit(c)">
                  <Icon name="settings" />
                </button>
                <button v-if="c.removable" class="ghost icon-only danger-icon" title="Удалить" aria-label="Удалить" @click="remove(c)">
                  <Icon name="trash" />
                </button>
              </div>
            </div>
            <div v-if="messages[c.name]" class="alert small" :class="messages[c.name]?.kind">
              <Icon :name="messages[c.name]?.kind === 'ok' ? 'check' : 'info'" /> {{ messages[c.name]?.text }}
            </div>
            <div v-else-if="c.state === 'error' && c.detail" class="alert small error"><Icon name="info" /> {{ c.detail }}</div>

            <form v-if="editing === c.name" class="edit" @submit.prevent="save(c)">
              <div class="fields">
                <div v-for="f in mainFields(c)" :key="f" :class="{ wide: f === 'bot_token' || f === 'password' }">
                  <label :for="c.name + f">{{ FIELD[f]?.label ?? f }}</label>
                  <input
                    :id="c.name + f"
                    v-model="form[f] as string"
                    :type="SECRET.includes(f) ? 'password' : 'text'"
                    :placeholder="FIELD[f]?.placeholder"
                    autocomplete="off"
                  />
                  <p v-if="FIELD[f]?.hint" class="small muted hint">{{ FIELD[f]?.hint }}</p>
                </div>
              </div>
              <details class="more small">
                <summary>Дополнительно</summary>
                <div class="fields">
                  <div v-for="f in extraFields(c)" :key="f">
                    <label :for="c.name + f">{{ FIELD[f]?.label ?? f }}</label>
                    <input :id="c.name + f" v-model="form[f] as string" :placeholder="FIELD[f]?.placeholder" autocomplete="off" />
                    <p v-if="FIELD[f]?.hint" class="small muted hint">{{ FIELD[f]?.hint }}</p>
                  </div>
                </div>
                <label class="check"><input v-model="form.test_service" type="checkbox" /> Это тестовый сервис (для проверки без настоящих писем)</label>
              </details>
              <div class="row">
                <button class="primary" type="submit" :disabled="busy === c.name"><Icon name="check" /> Сохранить и проверить</button>
                <button type="button" class="ghost" @click="editing = null">Отмена</button>
              </div>
            </form>
          </li>
        </ul>
      </section>

      <section v-if="can('admin') && services.length" class="card group">
        <div class="group-head"><h2><Icon name="plug" /> Сервисы компании</h2></div>
        <ul class="rows">
          <li v-for="c in services" :key="c.name" class="item" :class="{ open: editing === c.name }">
            <div class="row-main">
              <span class="kind" :class="c.state"><Icon :name="iconOf(c)" size="1.2rem" /></span>
              <div class="who">
                <b>{{ c.title }}</b>
                <span class="small muted">{{ SERVICE_ABOUT[c.name] }} {{ lastCheck(c).replace(/^./, (ch) => ch.toUpperCase()) }}.</span>
              </div>
              <span class="badge" :class="STATE[c.state]?.tone">{{ STATE[c.state]?.label }}</span>
              <span v-if="c.test_service" class="badge medium">тестовый</span>
              <div class="acts">
                <button class="ghost icon-only" :disabled="c.state === 'not_configured' || busy === c.name" title="Проверить связь" aria-label="Проверить связь" @click="check(c)"><Icon name="refresh" /></button>
                <button class="ghost icon-only" title="Настроить" aria-label="Настроить" @click="editing === c.name ? (editing = null) : edit(c)"><Icon name="settings" /></button>
              </div>
            </div>
            <div v-if="messages[c.name]" class="alert small" :class="messages[c.name]?.kind">{{ messages[c.name]?.text }}</div>
            <form v-if="editing === c.name" class="edit" @submit.prevent="save(c)">
              <div class="fields">
                <div v-for="f in c.fields" :key="f">
                  <label :for="c.name + f">{{ FIELD[f]?.label ?? f }}</label>
                  <input :id="c.name + f" v-model="form[f] as string" :type="SECRET.includes(f) ? 'password' : 'text'" autocomplete="off" />
                </div>
              </div>
              <label class="check"><input v-model="form.test_service" type="checkbox" /> Это тестовый сервис</label>
              <details class="more small"><summary>Технические подробности</summary><p class="muted">{{ c.contract }}</p></details>
              <div class="row">
                <button class="primary" type="submit"><Icon name="check" /> Сохранить и проверить</button>
                <button type="button" class="ghost" @click="editing = null">Отмена</button>
              </div>
            </form>
          </li>
        </ul>
      </section>
    </template>
  </div>
</template>

<style scoped>
.conn .card { max-width: 80rem; }
.group { padding: 0; margin-bottom: 1.25rem; overflow: hidden; }
.group-head { display: flex; align-items: center; gap: 0.75rem; padding: 1rem 1.25rem; border-bottom: 1px solid var(--line); flex-wrap: wrap; }
.group-head h2 { margin: 0; flex: 1; display: flex; align-items: center; gap: 0.5rem; }
.count { font-size: 0.8rem; font-weight: 600; color: var(--muted); background: var(--surface-2); box-shadow: inset 0 0 0 1px var(--line); border-radius: 99px; padding: 0 0.5rem; }
.empty-line { padding: 1rem 1.25rem; margin: 0; }
.rows { list-style: none; margin: 0; padding: 0; }
.item { border-bottom: 1px solid var(--line); padding: 0.85rem 1.25rem; }
.item:last-child { border-bottom: 0; }
.item.open { background: var(--surface-2); }
.row-main { display: flex; align-items: center; gap: 0.85rem; flex-wrap: wrap; }
.kind {
  width: 2.5rem; height: 2.5rem; border-radius: var(--radius-s); display: grid; place-items: center; flex: none;
  background: var(--accent-soft); color: var(--accent);
}
.kind.error { background: var(--danger-soft); color: var(--danger); }
.kind.ok { background: var(--ok-soft); color: var(--ok); }
.who { flex: 1 1 14rem; min-width: 0; display: flex; flex-direction: column; }
.who b { overflow-wrap: anywhere; }
.acts { display: flex; gap: 0.25rem; margin-left: auto; }
.danger-icon { color: var(--danger); }
.item .alert { margin: 0.6rem 0 0; }
.edit { margin-top: 0.85rem; padding-top: 0.85rem; border-top: 1px dashed var(--line); }
.fields { display: grid; grid-template-columns: repeat(auto-fill, minmax(14rem, 1fr)); gap: 0 1rem; }
.fields .wide { grid-column: 1 / -1; max-width: 36rem; }
.hint { margin: 0.25rem 0 0; }
.more { margin: 0.75rem 0; }
.more summary { cursor: pointer; color: var(--muted); }
.check { display: flex; align-items: center; gap: 0.5rem; color: var(--text); font-size: 0.9rem; margin-top: 0.6rem; }
.edit > .row { margin-top: 0.75rem; }
@media (max-width: 640px) {
  .hide-narrow { display: none; }
  .acts { width: 100%; justify-content: flex-end; }
}
</style>
