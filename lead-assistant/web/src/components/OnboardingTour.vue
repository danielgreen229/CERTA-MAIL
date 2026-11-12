<script setup lang="ts">
/**
 * Пошаговое обучение по кнопкам почты. Каждый шаг подсвечивает элемент и объясняет,
 * зачем он нужен. Шаги с письмом открывают настоящее письмо из списка.
 * Управление: «Далее» / «Назад», стрелки ← →, Esc — завершить.
 */
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { mail } from '../mailbox'
import { finish, later, startTour, tour } from '../onboarding'
import { can } from '../session'
import Icon from './Icon.vue'

interface Step {
  title: string
  text: string
  /** CSS-селектор подсвечиваемого элемента; нет — карточка по центру. */
  target?: string
  /** Куда перейти перед шагом: адрес или «первое письмо». */
  route?: string | 'lead'
  role?: 'supervisor' | 'admin'
}

const STEPS: Step[] = [
  { title: 'Добро пожаловать в почту Certa', text: 'Помощник читает письма клиентов из почты и Telegram, определяет категорию и срочность и готовит черновик ответа. Ваша задача — проверить и отправить. Пройдём по всем кнопкам — это займёт пару минут.' },
  { route: '/leads', target: 'a.nav-item.current', title: 'Почта', text: 'Главный раздел. Красное число — сколько писем ждут разбора или вашего решения.' },
  { route: '/leads', target: '#folders-inbox', title: 'Входящие по ящикам', text: 'Каждый почтовый ящик и Telegram-бот — своя папка. «Все письма» — общий список. Число — сколько писем ждут ответа.' },
  { route: '/leads', target: '#folders-inbox .expander', title: 'Срочность внутри ящика', text: 'Стрелка раскрывает ящик: письма по срочности — высокая, средняя, низкая. Начинайте с красной.' },
  { route: '/leads', target: '#folders-work', title: 'В работе', text: '«Ждут решения» — черновик готов. «На проверку» — помощник не уверен или есть риск. «Срочные» и «Просрочены» — то, что нельзя откладывать.' },
  { route: '/leads', target: '#folders-done', title: 'Решённые', text: 'Письма, по которым вы уже приняли, исправили или отклонили черновик.' },
  { route: '/leads', target: '.summary', title: 'Сводка', text: 'Четыре главных числа. Нажмите на любое — список покажет только эти письма. Повторное нажатие снимает фильтр.' },
  { route: '/leads', target: '.tabs', title: 'Категории', text: 'Продажи, жалобы, вопросы и спам — помощник определил категорию сам, вы можете её исправить.' },
  { route: '/leads', target: '.toolbar', title: 'Фильтры', text: 'Срочность и состояние сужают список. «Сбросить» возвращает все письма.' },
  { route: '/leads', target: '.sort-btn', title: 'Сначала важные', text: 'Поднимает наверх неразобранные письма по срочности: высокая, просроченные, ближайший срок ответа. Выбор запоминается.' },
  { route: '/leads', target: '.search', title: 'Поиск', text: 'Ищет по имени, адресу, тексту письма и номеру накладной или заказа.' },
  { route: '/leads', target: '.list tbody tr', title: 'Письмо в списке', text: 'Отправитель, тема, срочность и состояние. Красная полоса слева — срочное письмо без ответа. Нажмите на строку, чтобы открыть письмо.' },
  { route: 'lead', target: '.lead-dialog .headers', title: 'Письмо клиента', text: 'От кого, на какой ящик и когда пришло, полный текст. Ниже — что помощник понял из письма: маршрут, груз, сроки, номера.' },
  { route: 'lead', target: '.lead-dialog .cols > section:nth-child(2)', title: 'Оценка помощника', text: 'Категория, срочность и её основание — цитата из письма. Жёлтый блок «Проверьте сами» объясняет, на что посмотреть.' },
  { route: 'lead', target: '.lead-dialog .actions', title: 'Ваше решение', text: '«Принять» — черновик верный. «Исправить» — поменять категорию, срочность или текст. «Отклонить» — помощник ошибся, укажите причину. «Назначить» — выбрать ответственного из сотрудников или отдел.' },
  { route: 'lead', target: '.lead-dialog .reply', title: 'Ответ клиенту', text: 'Черновик уже в поле — поправьте и нажмите «Отправить ответ». Письмо уйдёт с того ящика, куда написал клиент, сообщение в Telegram — от того же бота. Повторная отправка спросит подтверждение.' },
  { route: '/leads', target: '.page-head .menu', title: 'Выгрузка', text: 'Сохраняет текущий список в Excel, PDF, Word или JSON — с учётом выбранной папки и фильтров.' },
  { route: '/leads', target: '.page-head .actions .primary', title: 'Разобрать новые', text: 'Новые письма разбираются сами в течение минуты. Кнопка — если хотите запустить разбор сразу.' },
  { route: '/leads', target: '.top-actions', title: 'Звук и тема', text: 'Колокольчик включает звук о новых письмах, следующая кнопка переключает светлую и тёмную тему. Справа — ваш профиль и выход.' },
  { route: '/leads', target: '.collapse-btn', title: 'Боковая панель', text: 'Стрелка сворачивает панель в полосу иконок. Ширину можно менять, потянув за правый край; длинные названия прокручиваются при наведении.' },
  { target: 'a.nav-item[href="/connectors"]', title: 'Почта и сервисы', text: 'Подключите свои почтовые ящики и Telegram-ботов — сколько угодно. Их письма будут приходить в «Почту» автоматически.' },
  { target: 'a.nav-item[href="/jobs"]', title: 'Разбор писем', text: 'Как помощник разбирает письма: идёт ли разбор сейчас и что было сделано раньше, со ссылками на срочные.' },
  { target: 'a.nav-item[href="/knowledge"]', title: 'База знаний', text: 'Документы компании: условия, документы, претензии. Подходящие фрагменты показываются прямо в окне письма.' },
  { target: 'a.nav-item[href="/quality"]', role: 'supervisor', title: 'Качество ответов', text: 'Для руководителя: сколько черновиков принято без правок, что чаще исправляют и почему отклоняют.' },
  { target: 'a.nav-item[href="/settings"]', title: 'Настройки', text: 'Пароль, тема и звук. Отсюда же можно пройти это обучение заново.' },
  { route: '/settings', target: '.settings .card:nth-of-type(3)', role: 'admin', title: 'Для администратора', text: 'Рабочее время и сроки ответа, отделы по категориям, сотрудники и роли, журнал действий, модель помощника.' },
  { title: 'Готово!', text: 'Вы знаете всё, чтобы работать с почтой: откройте срочное письмо, проверьте черновик и отправьте ответ. Обучение можно пройти снова в «Настройках».' },
]

const router = useRouter()
const steps = computed(() => STEPS.filter((s) => !s.role || can(s.role)))
const step = computed(() => steps.value[tour.index] ?? null)
const rect = ref<DOMRect | null>(null)
const card = ref<HTMLElement | null>(null)
const cardStyle = ref<Record<string, string>>({})

function firstLeadPath(): string | null {
  const leads = mail.data?.leads ?? []
  const lead = leads.find((l) => l.state === 'pending') ?? leads[0]
  return lead ? `/leads/${encodeURIComponent(lead.key)}` : null
}

async function waitFor(selector: string, ms = 2500): Promise<HTMLElement | null> {
  const start = performance.now()
  while (performance.now() - start < ms) {
    const el = document.querySelector<HTMLElement>(selector)
    if (el && el.getBoundingClientRect().width > 0) return el
    await new Promise((r) => setTimeout(r, 80))
  }
  return null
}

async function show() {
  const s = step.value
  if (!s) return
  rect.value = null
  if (s.route === 'lead') {
    const path = firstLeadPath()
    if (path && router.currentRoute.value.path !== path) await router.push(path)
  } else if (s.route && router.currentRoute.value.path !== s.route) {
    await router.push(s.route)
  }
  await nextTick()
  const el = s.target ? await waitFor(s.target) : null
  if (el) {
    el.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'instant' as ScrollBehavior })
    await new Promise((r) => requestAnimationFrame(r))
    rect.value = el.getBoundingClientRect()
  }
  await nextTick()
  place()
  card.value?.focus()
}

/** Карточка — под элементом, если помещается, иначе над ним или сбоку; без цели — по центру. */
function place() {
  const r = rect.value
  const box = card.value?.getBoundingClientRect()
  const w = box?.width ?? 360
  const h = box?.height ?? 200
  const vw = window.innerWidth
  const vh = window.innerHeight
  const gap = 14
  if (!r) {
    cardStyle.value = { left: `${Math.max(12, (vw - w) / 2)}px`, top: `${Math.max(12, (vh - h) / 2)}px` }
    return
  }
  let top = r.bottom + gap
  let left = r.left
  if (top + h > vh - 12) top = r.top - h - gap
  if (top < 12) {
    // Не влезает ни снизу, ни сверху — ставим сбоку от элемента.
    top = Math.min(Math.max(12, r.top), vh - h - 12)
    left = r.right + gap + w < vw ? r.right + gap : r.left - w - gap
  }
  left = Math.min(Math.max(12, left), vw - w - 12)
  cardStyle.value = { left: `${left}px`, top: `${top}px` }
}

const spot = computed(() => {
  const r = rect.value
  if (!r) return null
  const pad = 6
  return {
    left: `${r.left - pad}px`,
    top: `${r.top - pad}px`,
    width: `${r.width + pad * 2}px`,
    height: `${r.height + pad * 2}px`,
  }
})

function next() {
  if (tour.index < steps.value.length - 1) tour.index += 1
  else end('done')
}
function prev() {
  if (tour.index > 0) tour.index -= 1
}
function end(state: 'done' | 'skipped') {
  finish(state)
  if (router.currentRoute.value.path.startsWith('/leads/')) router.push('/leads')
}

function onKey(event: KeyboardEvent) {
  if (!tour.active) return
  if (event.key === 'ArrowRight') next()
  else if (event.key === 'ArrowLeft') prev()
  else if (event.key === 'Escape') {
    event.stopPropagation()
    end(tour.index >= steps.value.length - 1 ? 'done' : 'skipped')
  } else return
  event.preventDefault()
}
const onResize = () => tour.active && show()

watch(
  () => [tour.active, tour.index] as const,
  ([active]) => {
    if (active) {
      window.addEventListener('keydown', onKey, true)
      window.addEventListener('resize', onResize)
      show()
    } else {
      window.removeEventListener('keydown', onKey, true)
      window.removeEventListener('resize', onResize)
    }
  },
)
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey, true)
  window.removeEventListener('resize', onResize)
})
</script>

<template>
  <!-- Предложение пройти обучение: небольшое окно, не мешает работать. -->
  <div v-if="tour.offer && !tour.active" class="offer" role="dialog" aria-label="Обучение">
    <div class="offer-head"><Icon name="info" /> <b>Новая почта Certa</b></div>
    <p class="small">Покажем все кнопки по шагам — это займёт пару минут. Пройти обучение сейчас?</p>
    <div class="row">
      <button class="primary" @click="startTour"><Icon name="run" /> Начать</button>
      <button class="ghost" @click="later">Позже</button>
      <button class="ghost small-btn" @click="finish('skipped')">Не показывать</button>
    </div>
  </div>

  <div v-if="tour.active && step" class="tour" aria-live="polite">
    <div v-if="spot" class="spot" :style="spot"></div>
    <div v-else class="dim"></div>
    <div ref="card" class="tour-card" :style="cardStyle" role="dialog" :aria-label="step.title" tabindex="-1">
      <div class="tour-head">
        <span class="step-no num">{{ tour.index + 1 }} из {{ steps.length }}</span>
        <button class="ghost icon-only" aria-label="Завершить обучение" title="Завершить (Esc)" @click="end('skipped')">
          <Icon name="close" />
        </button>
      </div>
      <h3>{{ step.title }}</h3>
      <p>{{ step.text }}</p>
      <div class="bar" aria-hidden="true"><div :style="{ width: ((tour.index + 1) / steps.length) * 100 + '%' }"></div></div>
      <div class="tour-actions">
        <button v-if="tour.index > 0" class="ghost" @click="prev"><Icon name="back" /> Назад</button>
        <span class="grow"></span>
        <button class="primary" @click="next">
          {{ tour.index === steps.length - 1 ? 'Готово' : 'Далее' }}
          <Icon v-if="tour.index < steps.length - 1" name="back" class="flip" />
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.offer {
  position: fixed; left: 1.25rem; bottom: 1.25rem; z-index: 90; width: min(24rem, calc(100vw - 2.5rem));
  background: var(--surface); border: 1px solid var(--line); border-left: 4px solid var(--brand-red);
  border-radius: var(--radius); box-shadow: var(--shadow-pop); padding: 1rem 1.1rem;
}
.offer-head { display: flex; align-items: center; gap: 0.5rem; }
.offer p { margin: 0.4rem 0 0.75rem; color: var(--muted); }
.small-btn { font-size: 0.85rem; color: var(--muted); }
.tour { position: fixed; inset: 0; z-index: 100; pointer-events: none; }
.dim { position: fixed; inset: 0; background: rgb(15 21 32 / 0.55); pointer-events: auto; }
/* Подсветка: «окно» в затемнении вокруг элемента. */
.spot {
  position: fixed; border-radius: 10px; pointer-events: none;
  box-shadow: 0 0 0 4px var(--brand-red), 0 0 0 9999px rgb(15 21 32 / 0.55);
  transition: left 0.2s ease, top 0.2s ease, width 0.2s ease, height 0.2s ease;
}
.tour-card {
  position: fixed; width: min(23rem, calc(100vw - 24px)); pointer-events: auto; outline: none;
  background: var(--surface); color: var(--text); border-radius: var(--radius); padding: 1rem 1.15rem 1rem;
  box-shadow: var(--shadow-pop); border: 1px solid var(--line);
}
.tour-head { display: flex; align-items: center; justify-content: space-between; margin: -0.35rem -0.4rem 0 0; }
.step-no { font-size: 0.8rem; color: var(--muted); font-weight: 600; }
.tour-card h3 { margin: 0.2rem 0 0.4rem; font-size: 1.05rem; }
.tour-card p { margin: 0; color: var(--text); line-height: 1.5; }
.bar { height: 3px; background: var(--line); border-radius: 99px; margin: 0.9rem 0 0.75rem; overflow: hidden; }
.bar > div { height: 100%; background: var(--brand-red); transition: width 0.2s ease; }
.tour-actions { display: flex; align-items: center; gap: 0.5rem; }
.flip { transform: rotate(180deg); }
@media (prefers-reduced-motion: reduce) { .spot, .bar > div { transition: none; } }
</style>
