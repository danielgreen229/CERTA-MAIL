<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, ROLE } from './api'
import BrandLogo from './components/BrandLogo.vue'
import FolderNav from './components/FolderNav.vue'
import Icon, { type IconName } from './components/Icon.vue'
import { applyFolder, filters, loadMail, mail, startPolling, stopPolling, type FolderFilter } from './mailbox'
import { soundOn, toggleSound } from './notify'
import { session, can } from './session'
import { theme, nextTheme, THEME_TITLE } from './theme'

const router = useRouter()
const route = useRoute()
const menuOpen = ref(false)
const onMail = computed(() => route.path.startsWith('/leads'))
const waiting = computed(() => (mail.data?.counts.new ?? 0) + (mail.data?.counts.pending ?? 0))
const initials = computed(() =>
  (session.user?.name ?? '?').split(/\s+/).map((w) => w[0]).slice(0, 2).join('').toUpperCase(),
)
const themeIcon = computed<IconName>(() => ({ system: 'auto', light: 'sun', dark: 'moon' })[theme.value] as IconName)

interface NavItem { to: string; label: string; icon: IconName; role?: 'supervisor' | 'admin'; hint: string }
const NAV: NavItem[] = [
  { to: '/jobs', label: 'Разбор писем', icon: 'agent', hint: 'Как помощник разбирает новые письма' },
  { to: '/quality', label: 'Качество ответов', icon: 'quality', role: 'supervisor', hint: 'Сколько черновиков принято и почему правят' },
  { to: '/knowledge', label: 'База знаний', icon: 'book', hint: 'Документы, на которые опирается помощник' },
  { to: '/connectors', label: 'Почта и сервисы', icon: 'plug', hint: 'Свои почтовые ящики и Telegram-боты' },
  { to: '/settings', label: 'Настройки', icon: 'settings', hint: 'Сроки, отделы, пользователи' },
]

// Список писем и уведомления живут всё время, пока человек вошёл: звук слышен на любой странице.
watch(
  () => session.user?.id,
  (id) => {
    if (id && !session.user?.must_change_password) {
      loadMail(true)
      startPolling()
    } else stopPolling()
  },
  { immediate: true },
)
onUnmounted(stopPolling)
watch(() => route.fullPath, () => (menuOpen.value = false))

function openFolder(folder: FolderFilter) {
  applyFolder(folder, onMail.value)
  if (!onMail.value) router.push('/leads')
}

const search = ref(filters.q)
watch(() => filters.q, (q) => (search.value = q))
let debounce: number | undefined
function onSearch() {
  window.clearTimeout(debounce)
  debounce = window.setTimeout(() => {
    filters.q = search.value.trim()
    if (!onMail.value) router.push('/leads')
  }, 250)
}

// --- боковая панель: свернуть в полосу иконок и менять ширину перетаскиванием края ---
const SIDEBAR_KEY = 'leads.sidebar'
const DEFAULT_REM = 15.5
const MIN_REM = 12
const MAX_REM = 32
function loadSidebar(): { collapsed?: boolean; width?: number } {
  try {
    return JSON.parse(localStorage.getItem(SIDEBAR_KEY) ?? '{}') as { collapsed?: boolean; width?: number }
  } catch {
    return {}
  }
}
const savedSidebar = loadSidebar()
const collapsed = ref(!!savedSidebar.collapsed)
const widthRem = ref(Math.min(MAX_REM, Math.max(MIN_REM, savedSidebar.width ?? DEFAULT_REM)))
const wideQuery = window.matchMedia('(min-width: 1025px)')
const wide = ref(wideQuery.matches)
const onWide = (e: MediaQueryListEvent) => (wide.value = e.matches)
wideQuery.addEventListener('change', onWide)
onUnmounted(() => wideQuery.removeEventListener('change', onWide))
const rail = computed(() => collapsed.value && wide.value)
const shellStyle = computed(() => (wide.value ? { '--sidebar': rail.value ? '4.6rem' : `${widthRem.value}rem` } : {}))
watch([collapsed, widthRem], () => {
  try {
    localStorage.setItem(SIDEBAR_KEY, JSON.stringify({ collapsed: collapsed.value, width: widthRem.value }))
  } catch {
    /* настройка действует до перезагрузки */
  }
})
const resizing = ref(false)
function rootPx(): number {
  return parseFloat(getComputedStyle(document.documentElement).fontSize) || 15
}
function startResize(event: PointerEvent) {
  if (rail.value) return
  const startX = event.clientX
  const start = widthRem.value
  const px = rootPx()
  resizing.value = true
  const move = (e: PointerEvent) => {
    widthRem.value = Math.round(Math.min(MAX_REM, Math.max(MIN_REM, start + (e.clientX - startX) / px)) * 10) / 10
  }
  const up = () => {
    resizing.value = false
    window.removeEventListener('pointermove', move)
    window.removeEventListener('pointerup', up)
  }
  window.addEventListener('pointermove', move)
  window.addEventListener('pointerup', up)
}
function resizeByKey(event: KeyboardEvent) {
  if (event.key === 'ArrowLeft') widthRem.value = Math.max(MIN_REM, widthRem.value - 1)
  else if (event.key === 'ArrowRight') widthRem.value = Math.min(MAX_REM, widthRem.value + 1)
  else return
  event.preventDefault()
}

async function logout() {
  await api.post('/api/auth/logout').catch(() => undefined)
  session.user = null
  router.push('/login')
}
</script>

<template>
  <div
    v-if="session.user && !route.meta.public && !session.user.must_change_password"
    class="shell"
    :class="{ 'menu-open': menuOpen, rail, resizing }"
    :style="shellStyle"
  >
    <aside class="sidebar" aria-label="Разделы">
      <div class="side-head">
        <RouterLink to="/leads" class="logo" aria-label="Certa — на главную"><BrandLogo :compact="rail" /></RouterLink>
        <button
          class="ghost icon-only collapse-btn"
          :title="rail ? 'Развернуть панель' : 'Свернуть панель'"
          :aria-label="rail ? 'Развернуть панель' : 'Свернуть панель'"
          :aria-expanded="!rail"
          @click="collapsed = !collapsed"
        >
          <Icon name="back" class="collapse-icon" />
        </button>
      </div>
      <nav class="nav">
        <RouterLink to="/leads" class="nav-item" :class="{ current: onMail }" title="Почта" @click="applyFolder({})">
          <Icon name="inbox" size="1.2rem" />
          <span v-marquee class="label">Почта</span>
          <span v-if="waiting" class="nav-count num">{{ waiting }}</span>
        </RouterLink>
        <FolderNav v-if="mail.data && onMail && !rail" class="mail-folders" @select="openFolder" />
        <div class="nav-sep" role="separator"></div>
        <template v-for="item in NAV" :key="item.to">
          <RouterLink v-if="!item.role || can(item.role)" :to="item.to" class="nav-item" :title="rail ? item.label : item.hint">
            <Icon :name="item.icon" size="1.2rem" />
            <span v-marquee class="label">{{ item.label }}</span>
          </RouterLink>
        </template>
      </nav>
      <div
        v-if="!rail"
        class="resizer"
        role="separator"
        aria-orientation="vertical"
        aria-label="Ширина панели: тяните или используйте стрелки; двойной щелчок — обычная ширина"
        title="Потяните, чтобы изменить ширину. Двойной щелчок — обычная ширина."
        tabindex="0"
        @pointerdown.prevent="startResize"
        @dblclick="widthRem = DEFAULT_REM"
        @keydown="resizeByKey"
      ></div>
    </aside>
    <div class="scrim" aria-hidden="true" @click="menuOpen = false"></div>

    <header class="topbar">
      <button class="ghost icon-only menu-btn" aria-label="Открыть меню" @click="menuOpen = !menuOpen">
        <Icon name="menu" />
      </button>
      <RouterLink to="/leads" class="topbar-logo" aria-label="Certa"><BrandLogo compact /></RouterLink>
      <label class="search">
        <span class="visually-hidden">Поиск по письмам</span>
        <Icon name="search" class="search-icon" />
        <input
          v-model="search"
          type="search"
          placeholder="Поиск: имя, адрес, текст, номер накладной"
          @input="onSearch"
        />
      </label>
      <div class="top-actions">
        <RouterLink v-if="session.demoSettings && can('admin')" to="/settings" class="demo" title="Сроки реакции и отделы пока примерные — настройте их">
          <Icon name="info" size="1rem" /> <span>Примерные настройки</span>
        </RouterLink>
        <button
          class="ghost icon-only"
          :aria-pressed="soundOn"
          :title="soundOn ? 'Звук о новых письмах включён' : 'Звук о новых письмах выключен'"
          :aria-label="soundOn ? 'Выключить звук о новых письмах' : 'Включить звук о новых письмах'"
          @click="toggleSound"
        >
          <Icon :name="soundOn ? 'bell' : 'bellOff'" />
        </button>
        <button class="ghost icon-only" :title="THEME_TITLE[theme]" :aria-label="THEME_TITLE[theme]" @click="nextTheme">
          <Icon :name="themeIcon" />
        </button>
        <div class="user">
          <span class="avatar" aria-hidden="true">{{ initials }}</span>
          <span class="who">
            <b>{{ session.user.name }}</b>
            <span class="muted small">{{ ROLE[session.user.role] }}</span>
          </span>
          <button class="ghost icon-only" title="Выйти" aria-label="Выйти" @click="logout"><Icon name="logout" /></button>
        </div>
      </div>
    </header>

    <main class="content">
      <RouterView />
    </main>

    <div v-if="mail.toast" class="toast" role="status" @click="mail.toast = ''">
      <Icon name="mail" /> {{ mail.toast }}
    </div>
  </div>
  <RouterView v-else />
</template>

<style scoped>
.shell {
  display: grid; min-height: 100vh;
  grid-template-columns: var(--sidebar) minmax(0, 1fr);
  grid-template-rows: var(--topbar) 1fr;
  grid-template-areas: 'side top' 'side main';
}
.sidebar {
  grid-area: side; position: sticky; top: 0; height: 100vh; overflow-y: auto;
  background: var(--surface); border-right: 1px solid var(--line);
  padding: 0 0.75rem 1.25rem; display: flex; flex-direction: column; scrollbar-width: thin;
}
.side-head { display: flex; align-items: center; gap: 0.25rem; margin: 0.85rem 0 1.1rem 0.55rem; }
.logo { display: block; height: 2.6rem; flex: 1; min-width: 0; }
.collapse-btn { flex: none; color: var(--muted); }
.collapse-icon { transition: transform 0.2s ease; }
.rail .collapse-icon { transform: rotate(180deg); }
.sidebar { position: sticky; }
.resizer {
  position: absolute; top: 0; right: 0; width: 6px; height: 100%; cursor: col-resize; z-index: 3;
  background: transparent; transition: background-color 0.15s;
}
.resizer:hover, .resizer:focus-visible, .resizing .resizer { background: color-mix(in srgb, var(--accent) 35%, transparent); outline: none; }
.resizing { user-select: none; cursor: col-resize; }
/* Свёрнутая панель: только иконки, счётчик — точкой, название — в подсказке. */
.rail .sidebar { padding: 0 0.5rem 1.25rem; overflow-x: hidden; }
.rail .side-head { flex-direction: column; margin: 0.85rem 0 1rem; gap: 0.6rem; }
.rail .logo { height: 2.1rem; flex: none; }
.rail .nav-item { justify-content: center; padding: 0.55rem 0; position: relative; }
.rail .nav-item .label { display: none; }
.rail .nav-count {
  position: absolute; top: 0.3rem; right: 0.45rem; min-width: 0; width: 0.6rem; height: 0.6rem; padding: 0;
  font-size: 0; line-height: 0; box-shadow: 0 0 0 2px var(--surface);
}
.nav-item .label { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.nav { display: flex; flex-direction: column; gap: 2px; }
.nav-item {
  display: flex; align-items: center; gap: 0.7rem; padding: 0.5rem 0.65rem; border-radius: var(--radius-s);
  color: var(--text); text-decoration: none; font-weight: 520; min-height: 2.5rem;
}
.nav-item :deep(.icon) { color: var(--muted); }
.nav-item:hover { background: var(--accent-soft); }
.nav-item.router-link-active, .nav-item.current { background: var(--accent-soft); color: var(--accent); font-weight: 640; }
.nav-item.router-link-active :deep(.icon), .nav-item.current :deep(.icon) { color: var(--accent); }
.nav-item .label { flex: 1; }
.nav-count {
  font-size: 0.8rem; font-weight: 650; color: #fff; background: var(--brand-red);
  border-radius: 99px; padding: 0 0.45rem; min-width: 1.5rem; text-align: center; line-height: 1.5rem;
}
.mail-folders { margin: 0.2rem 0 0.4rem 0.4rem; padding-left: 0.4rem; border-left: 1px solid var(--line); }
.nav-sep { height: 1px; background: var(--line); margin: 0.6rem 0.4rem; }

.topbar {
  grid-area: top; position: sticky; top: 0; z-index: 10; display: flex; align-items: center; gap: 0.75rem;
  padding: 0 1.75rem; background: color-mix(in srgb, var(--surface) 92%, transparent);
  backdrop-filter: blur(8px); border-bottom: 1px solid var(--line);
}
.menu-btn, .topbar-logo { display: none; }
.search { position: relative; flex: 1; max-width: 34rem; margin: 0; color: var(--text); font-size: 1rem; }
.search-icon { position: absolute; left: 0.75rem; top: 50%; transform: translateY(-50%); color: var(--muted); pointer-events: none; }
.search input { padding-left: 2.4rem; background: var(--surface-2); border-color: var(--line); }
.top-actions { margin-left: auto; display: flex; align-items: center; gap: 0.35rem; }
.demo {
  display: inline-flex; align-items: center; gap: 0.35rem; margin-right: 0.4rem; padding: 0.25rem 0.65rem;
  border-radius: 99px; background: var(--warn-soft); color: var(--warn); font-size: 0.82rem; text-decoration: none;
}
.user { display: flex; align-items: center; gap: 0.6rem; margin-left: 0.5rem; padding-left: 0.85rem; border-left: 1px solid var(--line); }
.avatar {
  width: 2.25rem; height: 2.25rem; border-radius: 50%; display: grid; place-items: center; flex: none;
  background: var(--brand-navy); color: #fff; font-size: 0.82rem; font-weight: 650; letter-spacing: 0.02em;
}
.who { display: flex; flex-direction: column; line-height: 1.2; }
.who b { font-weight: 600; font-size: 0.92rem; }
.content { grid-area: main; min-width: 0; }
.scrim { display: none; }
.toast {
  position: fixed; right: 1.25rem; bottom: 1.25rem; z-index: 60; cursor: pointer;
  display: flex; align-items: center; gap: 0.6rem; padding: 0.8rem 1.1rem; border-radius: var(--radius);
  background: var(--brand-navy); color: #fff; font-weight: 600; box-shadow: var(--shadow-pop);
  border-left: 4px solid var(--brand-red);
}
.visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }

@media (max-width: 1280px) {
  .demo span { display: none; }
  .who { display: none; }
}
/* Планшет и телефон: меню выезжает слева по кнопке. */
@media (max-width: 1024px) {
  .shell { grid-template-columns: minmax(0, 1fr); grid-template-areas: 'top' 'main'; }
  .sidebar {
    position: fixed; z-index: 50; left: 0; top: 0; bottom: 0; width: min(19rem, 86vw);
    transform: translateX(-102%); transition: transform 0.2s ease; box-shadow: var(--shadow-pop);
  }
  .menu-open .sidebar { transform: none; }
  .menu-open .scrim { display: block; position: fixed; inset: 0; z-index: 40; background: rgb(15 21 32 / 0.45); }
  .menu-btn { display: inline-flex; }
  .collapse-btn, .resizer { display: none; }
  .topbar { padding: 0 1rem; gap: 0.5rem; }
  .topbar-logo { display: block; height: 1.9rem; flex: none; }
}
@media (max-width: 640px) {
  .user { padding-left: 0.4rem; margin-left: 0; border: 0; }
  .avatar { display: none; }
  .search input::placeholder { color: transparent; }
  .demo { display: none; }
}
</style>
