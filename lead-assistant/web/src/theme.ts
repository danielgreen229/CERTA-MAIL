import { ref, watch } from 'vue'

/** Тема интерфейса: как в системе, всегда светлая или всегда тёмная. Выбор хранится в браузере. */
export type ThemeMode = 'system' | 'light' | 'dark'

const STORAGE_KEY = 'leads.theme'
const MODES: ThemeMode[] = ['system', 'light', 'dark']

export const THEME_TITLE: Record<ThemeMode, string> = {
  system: 'Тема: как в системе',
  light: 'Тема: светлая',
  dark: 'Тема: тёмная',
}
export const THEME_ICON: Record<ThemeMode, string> = { system: '◐', light: '☀', dark: '☾' }

function stored(): ThemeMode {
  try {
    const value = localStorage.getItem(STORAGE_KEY)
    return MODES.includes(value as ThemeMode) ? (value as ThemeMode) : 'system'
  } catch {
    return 'system'
  }
}

export const theme = ref<ThemeMode>(stored())

function apply(mode: ThemeMode) {
  const root = document.documentElement
  if (mode === 'system') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', mode)
}

apply(theme.value)
watch(theme, (mode) => {
  apply(mode)
  try {
    localStorage.setItem(STORAGE_KEY, mode)
  } catch {
    /* хранилище недоступно — выбор действует до перезагрузки */
  }
})

export function nextTheme() {
  theme.value = MODES[(MODES.indexOf(theme.value) + 1) % MODES.length] ?? 'system'
}
