<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api, ApiError, CATEGORY, PRIORITY, formatDate, leadUrl, type Found, type LeadDetail } from '../api'
import Icon from './Icon.vue'

const props = defineProps<{ leadKey: string }>()
const emit = defineEmits<{ close: []; changed: [] }>()

const lead = ref<LeadDetail | null>(null)
const loading = ref(true)
const error = ref('')
const actionError = ref('')
const notice = ref('')
const busy = ref(false)
const mode = ref<'view' | 'correct' | 'reject' | 'assign'>('view')
const form = ref({ category: '', priority: '', draft_reply: '', reason: '', assignee: '', due_at: '' })
const chunk = ref<{ text: string; source: string } | null>(null)

async function load() {
  loading.value = true
  error.value = ''
  try {
    lead.value = await api.get<LeadDetail>(leadUrl(props.leadKey))
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось загрузить заявку'
    lead.value = null
  } finally {
    loading.value = false
  }
}

watch(() => props.leadKey, () => {
  mode.value = 'view'
  notice.value = ''
  actionError.value = ''
  load()
}, { immediate: true })

const current = computed(() => {
  const l = lead.value
  if (!l?.result) return null
  const d = l.decision && l.decision.action !== 'reject' ? l.decision : null
  return {
    category: d?.category ?? l.result.category,
    priority: d?.priority ?? l.result.priority,
    draft_reply: d?.draft_reply ?? l.result.draft_reply,
    approved: !!d,
  }
})
const analysis = computed(() => (lead.value?.result?.analysis ?? {}) as Record<string, string | boolean | null>)

function startCorrect() {
  const c = current.value
  if (!c) return
  form.value.category = c.category ?? 'question'
  form.value.priority = c.priority ?? 'medium'
  form.value.draft_reply = c.draft_reply ?? ''
  mode.value = 'correct'
}

function startAssign() {
  form.value.assignee = lead.value?.assignee ?? ''
  form.value.due_at = lead.value?.due_at ? lead.value.due_at.slice(0, 16) : ''
  mode.value = 'assign'
}

async function decide(action: 'accept' | 'correct' | 'reject') {
  if (!lead.value?.result) return
  busy.value = true
  actionError.value = ''
  notice.value = ''
  const payload: Record<string, unknown> = { action, result_version: lead.value.result.version }
  if (action === 'correct') {
    payload.category = form.value.category
    payload.priority = form.value.priority
    payload.draft_reply = form.value.category === 'spam' ? null : form.value.draft_reply
  }
  if (action === 'reject') payload.reason = form.value.reason
  try {
    const res = await api.post<{ lead: LeadDetail; warnings: string[] }>(`${leadUrl(props.leadKey)}/decision`, payload)
    lead.value = res.lead
    mode.value = 'view'
    notice.value = res.warnings.length
      ? `Сохранено. Проверьте черновик: ${res.warnings.join('; ')}`
      : { accept: 'Принято', correct: 'Исправление сохранено', reject: 'Отклонено' }[action]
    emit('changed')
  } catch (e) {
    actionError.value = e instanceof ApiError ? e.message : 'Не удалось сохранить решение'
    if (e instanceof ApiError && e.code === 'CONFLICT') await load()
  } finally {
    busy.value = false
  }
}

async function saveAssign() {
  busy.value = true
  actionError.value = ''
  try {
    const due = form.value.due_at ? new Date(form.value.due_at).toISOString() : null
    await api.post(`${leadUrl(props.leadKey)}/assign`, { assignee: form.value.assignee, due_at: due })
    mode.value = 'view'
    notice.value = 'Назначение сохранено'
    await load()
    emit('changed')
  } catch (e) {
    actionError.value = e instanceof ApiError ? e.message : 'Не удалось сохранить назначение'
  } finally {
    busy.value = false
  }
}

async function openChunk(id: number, source: string) {
  try {
    const data = await api.get<{ text: string }>(`/api/kb/chunks/${id}`)
    chunk.value = { text: data.text, source }
  } catch (e) {
    actionError.value = e instanceof ApiError ? e.message : 'Фрагмент недоступен'
  }
}

function show(item: Found): string {
  const v = item.value as Record<string, unknown> | string | number
  if (typeof v !== 'object' || v === null) return String(v)
  if ('from' in v || 'to' in v) return `${v.from ?? '?'} → ${v.to ?? '?'}`
  if ('kg' in v) return `${v.amount} ${v.unit}`
  if ('number' in v) return `${v.kind} № ${v.number}`
  if ('amount' in v) return `${v.amount} ${v.unit}`
  return JSON.stringify(v)
}

const actionTitle: Record<string, string> = { accept: 'Принято', correct: 'Исправлено', reject: 'Отклонено' }

// --- ответ клиенту ---
const replyText = ref('')
const sending = ref(false)
const alreadySent = computed(() => (lead.value?.replies ?? []).some((r) => r.status === 'sent'))
watch(
  () => [props.leadKey, current.value?.draft_reply] as const,
  () => {
    replyText.value = current.value?.draft_reply ?? ''
  },
  { immediate: true },
)

async function sendReply() {
  const l = lead.value
  if (!l || !replyText.value.trim()) return
  const again = alreadySent.value
  const question = again
    ? `Ответ этому клиенту уже отправлялся. Отправить ещё раз на ${l.reply.to}?`
    : `Отправить ответ на ${l.reply.to}?`
  if (!window.confirm(question)) return
  sending.value = true
  actionError.value = ''
  notice.value = ''
  try {
    const res = await api.post<{ lead: LeadDetail }>(`${leadUrl(props.leadKey)}/reply`, { text: replyText.value, force: again })
    lead.value = res.lead
    notice.value = `Ответ отправлен на ${res.lead.reply.to}`
    emit('changed')
  } catch (e) {
    actionError.value = e instanceof ApiError ? e.message : 'Не удалось отправить ответ'
    await load()
  } finally {
    sending.value = false
  }
}

const foundFields = computed(() => {
  const l = lead.value
  if (!l) return {}
  return Object.fromEntries(Object.entries(l.field_titles).filter(([k]) => l.extraction.fields[k]?.length))
})

const channelTitle: Record<string, string> = { email: 'Почта', telegram: 'Telegram' }
const heading = computed(() => {
  const l = lead.value?.lead
  if (!l) return 'Загрузка…'
  if (l.subject) return String(l.subject)
  const first = String(l.text ?? '').split('\n')[0] ?? ''
  return (first.startsWith('Тема: ') ? first.slice(6) : first).slice(0, 120) || 'Без темы'
})
</script>

<template>
  <article class="card">
    <div class="row" style="justify-content: space-between">
      <div class="title">
        <span class="small muted">Письмо № {{ leadKey.replace(/"/g, '') }}</span>
        <h2>{{ heading }}</h2>
      </div>
      <button class="ghost icon-only" aria-label="Закрыть" title="Закрыть (Esc)" @click="emit('close')"><Icon name="close" /></button>
    </div>
    <div v-if="loading" class="empty"><span class="spinner"></span> Загрузка…</div>
    <div v-else-if="error" class="alert error">{{ error }} <button @click="load">Повторить</button></div>
    <template v-else-if="lead">
      <div class="row small">
        <span class="badge" :class="{ gray: lead.state !== 'pending' }">{{ lead.state_title }}</span>

      </div>
      <div v-if="notice" class="alert ok">{{ notice }}</div>
      <div v-if="actionError" class="alert error">{{ actionError }}</div>

      <div v-if="lead.review_reasons.length && lead.state === 'pending'" class="alert warn">
        <Icon name="flag" /><div><strong>Проверьте сами:</strong>
        <ul><li v-for="r in lead.review_reasons" :key="r.code + r.text">{{ r.text }}</li></ul></div>
      </div>

      <div class="cols">
        <section>
          <h3><Icon name="mail" /> Письмо клиента</h3>
          <dl class="headers small">
            <dt>От</dt>
            <dd>{{ lead.lead.name }} <span class="muted">&lt;{{ lead.lead.contact || 'контакт не указан' }}&gt;</span></dd>
            <template v-if="lead.lead.inbox">
              <dt>Кому</dt>
              <dd>{{ lead.lead.inbox }}</dd>
            </template>
            <dt>Канал</dt>
            <dd>{{ channelTitle[String(lead.lead.channel)] ?? lead.lead.channel }}</dd>
            <dt>Дата</dt>
            <dd>{{ formatDate(String(lead.lead.date ?? '')) }}</dd>
          </dl>
          <pre class="source">{{ lead.lead.text }}</pre>

          <h3><Icon name="truck" /> Что понял помощник</h3>
          <table class="small">
            <tbody>
              <tr v-for="(title, field) in foundFields" :key="field">
                <th>{{ title }}</th>
                <td>
                  <template v-if="lead.extraction.fields[field]?.length">
                    <div v-for="(item, i) in lead.extraction.fields[field]" :key="i">
                      {{ show(item) }} <span class="muted">— «{{ item.quote }}»</span>
                    </div>
                  </template>

                </td>
              </tr>
            </tbody>
          </table>
          <div v-for="c in lead.extraction.contradictions" :key="c" class="alert warn small">{{ c }}</div>
          <div v-if="lead.extraction.missing.length" class="small muted" style="margin-top: 6px">
            Не хватает: {{ lead.extraction.missing.join(', ') }}
          </div>

          <template v-if="lead.shipments.length">
            <h3><Icon name="truck" /> Статус груза</h3>
            <div v-for="s in lead.shipments" :key="s.number" class="small">
              № {{ s.number }}: <b>{{ s.data?.status ?? s.error }}</b>
              <span v-if="s.data?.eta"> · ожидается {{ s.data.eta }}</span>
              <div class="muted">источник: {{ s.source }} · получено {{ formatDate(s.fetched_at) }}</div>
            </div>
          </template>
        </section>

        <section>
          <h3><Icon name="agent" /> Оценка помощника</h3>
          <div v-if="!lead.result" class="muted">Заявка ещё не обработана агентом. Запустите «Обработать новые».</div>
          <template v-else-if="current">
            <div class="row">
              <span class="badge gray">{{ CATEGORY[current.category ?? ''] ?? current.category }}</span>
              <span class="badge" :class="current.priority ?? ''">{{ PRIORITY[current.priority ?? ''] ?? current.priority }}</span>
              <span v-if="current.approved" class="badge low">согласовано</span>
            </div>
            <div class="small" style="margin-top: 8px">
              <div><b>Основание приоритета:</b> {{ analysis.urgency_basis || (lead.priority === 'high' ? '—' : 'срока или последствия из заявки не найдено') }}</div>
              <div v-if="analysis.manager_check"><b>Проверить:</b> {{ analysis.manager_check }}</div>
              <div><b>Следующий шаг:</b> {{ analysis.next_action || (current.category === 'spam' ? 'не отвечать' : 'связаться с клиентом по черновику') }}</div>
            </div>
            <h3><Icon name="edit" /> Черновик ответа</h3>
            <pre v-if="current.draft_reply && !lead.reply.available" class="draft">{{ current.draft_reply }}</pre>
            <div v-else-if="!current.draft_reply" class="muted">Для спама ответ не готовится.</div>
            <div v-else class="small muted">Текст черновика — в поле «Ответ клиенту» ниже: поправьте и отправьте.</div>

            <div v-if="lead.decision" class="small muted" style="margin-top: 6px">
              {{ actionTitle[lead.decision.action] }}: {{ lead.decision.user }}, {{ formatDate(lead.decision.created_at) }}
              <span v-if="lead.decision.reason"> · причина: {{ lead.decision.reason }}</span>
            </div>

            <div v-if="mode === 'view'" class="row actions">
              <button class="ok" :disabled="busy || lead.decision?.action === 'accept'" title="Черновик и оценка верны" @click="decide('accept')"><Icon name="check" /> Принять</button>
              <button :disabled="busy" title="Поправить категорию, срочность или текст" @click="startCorrect"><Icon name="edit" /> Исправить</button>
              <button class="danger" :disabled="busy" title="Помощник ошибся — укажите почему" @click="mode = 'reject'"><Icon name="reject" /> Отклонить</button>
              <button class="ghost" :disabled="busy" title="Сменить ответственного или срок" @click="startAssign"><Icon name="assign" /> Назначить</button>
            </div>

            <form v-if="mode === 'correct'" class="sub" @submit.prevent="decide('correct')">
              <div class="row">
                <div class="grow">
                  <label for="cat">Категория</label>
                  <select id="cat" v-model="form.category">
                    <option v-for="(t, k) in CATEGORY" :key="k" :value="k">{{ t }}</option>
                  </select>
                </div>
                <div class="grow">
                  <label for="pri">Приоритет</label>
                  <select id="pri" v-model="form.priority">
                    <option v-for="(t, k) in PRIORITY" :key="k" :value="k">{{ t }}</option>
                  </select>
                </div>
              </div>
              <template v-if="form.category !== 'spam'">
                <label for="draft">Черновик</label>
                <textarea id="draft" v-model="form.draft_reply" required></textarea>
              </template>
              <div class="row actions">
                <button class="primary" type="submit" :disabled="busy">Сохранить исправление</button>
                <button type="button" @click="mode = 'view'">Отмена</button>
              </div>
            </form>

            <form v-if="mode === 'reject'" class="sub" @submit.prevent="decide('reject')">
              <label for="reason">Причина отклонения</label>
              <input id="reason" v-model="form.reason" required placeholder="Например: неверно понята суть обращения" />
              <div class="row actions">
                <button class="danger" type="submit" :disabled="busy">Отклонить</button>
                <button type="button" @click="mode = 'view'">Отмена</button>
              </div>
            </form>
          </template>

          <form v-if="mode === 'assign'" class="sub" @submit.prevent="saveAssign">
            <label for="assignee">Ответственный</label>
            <input id="assignee" v-model="form.assignee" />
            <label for="due">Срок реакции</label>
            <input id="due" v-model="form.due_at" type="datetime-local" />
            <div class="row actions">
              <button class="primary" type="submit" :disabled="busy">Сохранить</button>
              <button type="button" @click="mode = 'view'">Отмена</button>
            </div>
          </form>

          <section class="reply">
            <h3><Icon name="send" /> Ответ клиенту</h3>
            <template v-if="lead.reply.available">
              <div class="small muted">
                Кому: <b>{{ lead.reply.to }}</b> · от: {{ lead.reply.from }} · тема: {{ lead.reply.subject }}
              </div>
              <textarea
                v-model="replyText"
                class="reply-text"
                rows="6"
                aria-label="Текст ответа"
                placeholder="Текст ответа клиенту"
              ></textarea>
              <div class="row actions">
                <button class="primary" :disabled="sending || !replyText.trim()" @click="sendReply">
                  <Icon name="send" /> {{ sending ? 'Отправка…' : alreadySent ? 'Отправить ещё раз' : 'Отправить ответ' }}
                </button>
                <span v-if="current && replyText !== (current.draft_reply ?? '')" class="small muted">изменён относительно черновика</span>
              </div>
            </template>
            <div v-else class="small muted">{{ lead.reply.reason }}</div>
            <ul v-if="lead.replies.length" class="sent small">
              <li v-for="r in lead.replies" :key="r.id" :class="r.status">
                <b>{{ r.status === 'sent' ? '✓ Отправлено' : '✕ Не отправлено' }}</b>
                {{ formatDate(r.at) }} · {{ r.user }} → {{ r.to }}
                <div v-if="r.error" class="err">{{ r.error }}</div>
              </li>
            </ul>
          </section>

          <div class="small" style="margin-top: 10px">
            <b>Ответственный:</b> {{ lead.assignee || 'не назначен' }} ·
            <b>Срок реакции:</b> <span :class="{ late: lead.overdue }">{{ formatDate(lead.due_at) }}</span>
          </div>

          <h3><Icon name="book" /> Из базы знаний</h3>
          <div v-for="c in lead.knowledge.conflicts" :key="c" class="alert warn small">{{ c }} — проверьте вручную.</div>
          <div v-if="!lead.knowledge.results.length" class="small muted">Подходящих действующих документов не найдено.</div>
          <div v-for="hit in lead.knowledge.results" :key="hit.chunk_id" class="hit small">
            <div class="quote">{{ hit.fragment.slice(0, 240) }}{{ hit.fragment.length > 240 ? '…' : '' }}</div>
            <button class="link" @click="openChunk(hit.chunk_id, hit.source)">{{ hit.source }}</button>
          </div>
        </section>
      </div>

      <h3><Icon name="calendar" /> История</h3>
      <ol class="history small">
        <li v-for="(h, i) in lead.history" :key="i">
          <span class="muted">{{ formatDate(h.at) }}</span>
          <template v-if="h.type === 'result'">
            — результат агента, версия {{ h.version }} ({{ h.category }}, {{ h.priority }}){{ h.run_id ? `, прогон ${h.run_id}` : '' }}
          </template>
          <template v-else>
            — {{ actionTitle[String(h.action)] }} ({{ h.user }}) к версии {{ h.result_version }}
            <span v-if="h.changes && Object.keys(h.changes as object).length">: изменено {{ Object.keys(h.changes as object).join(', ') }}</span>
            <span v-if="h.reason">: {{ h.reason }}</span>
          </template>
        </li>
      </ol>
    </template>

    <div v-if="chunk" class="modal" @click.self="chunk = null">
      <div class="card">
        <div class="row" style="justify-content: space-between">
          <strong>{{ chunk.source }}</strong>
          <button @click="chunk = null">Закрыть</button>
        </div>
        <pre style="margin-top: 8px">{{ chunk.text }}</pre>
      </div>
    </div>
  </article>
</template>

<style scoped>
.card { padding: 1.5rem 1.75rem; }
.title { min-width: 0; flex: 1; }
.title h2 { font-size: 1.35rem; margin: 0.1rem 0 0; overflow-wrap: anywhere; }
h3 { display: flex; align-items: center; gap: 0.45rem; }
h3 :deep(.icon) { color: var(--muted); }
.cols { display: grid; grid-template-columns: 1fr 1fr; gap: 2rem; margin-top: 0.5rem; }
.headers { display: grid; grid-template-columns: auto 1fr; gap: 2px 10px; margin: 0 0 8px; }
.headers dt { color: var(--muted); }
.headers dd { margin: 0; overflow-wrap: anywhere; }
.reply { margin-top: 14px; padding-top: 4px; border-top: 1px solid var(--line); }
.reply-text { width: 100%; margin-top: 6px; resize: vertical; min-height: 120px; }
.sent { list-style: none; padding: 0; margin: 8px 0 0; display: grid; gap: 4px; }
.sent li.sent b { color: var(--ok); }
.sent li.failed b, .sent .err { color: var(--danger); }
.source, .draft { background: var(--bg); border: 1px solid var(--line); border-radius: 8px; padding: 10px; }
.actions { margin-top: 10px; }
.sub { margin-top: 10px; border-top: 1px dashed var(--line); padding-top: 6px; }
.late { color: var(--danger); font-weight: 600; }
.hit { margin: 6px 0; }
button.link { border: 0; background: none; color: var(--accent); padding: 0; min-height: 0; text-decoration: underline; }
.history { padding-left: 18px; }
th { width: 38%; }
ul { margin: 4px 0 0; padding-left: 18px; }
.modal { position: fixed; inset: 0; background: rgba(0, 0, 0, .45); display: grid; place-items: center; padding: 16px; z-index: 20; }
.modal .card { max-width: 720px; width: 100%; max-height: 80vh; overflow: auto; }
@media (max-width: 1100px) { .cols { grid-template-columns: 1fr; gap: 0.5rem; } }
@media (max-width: 760px) { .card { padding: 1rem; border-radius: 0; } }
</style>
