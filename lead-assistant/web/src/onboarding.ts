import { reactive } from 'vue'

/**
 * Обучение: пошаговый тур по кнопкам. Предлагается один раз — небольшим окном после входа;
 * пройденное или отклонённое обучение запоминается в браузере (localStorage).
 * «Позже» скрывает предложение до следующего входа (sessionStorage).
 */
const DONE_KEY = 'leads.onboarding'
const LATER_KEY = 'leads.onboarding.later'

export type OnboardingState = 'done' | 'skipped' | null

function read(storage: Storage, key: string): string | null {
  try {
    return storage.getItem(key)
  } catch {
    return null
  }
}
function write(storage: Storage, key: string, value: string) {
  try {
    storage.setItem(key, value)
  } catch {
    /* хранилище недоступно — обучение предложится снова */
  }
}

export const tour = reactive({
  /** Небольшое окно с предложением пройти обучение. */
  offer: false,
  active: false,
  index: 0,
})

export function onboardingState(): OnboardingState {
  const value = read(localStorage, DONE_KEY)
  return value === 'done' || value === 'skipped' ? value : null
}

/** Показать предложение, если обучение ещё не пройдено и не отложено в этой сессии. */
export function maybeOffer() {
  if (!onboardingState() && read(sessionStorage, LATER_KEY) !== '1' && !tour.active) tour.offer = true
}

export function startTour() {
  tour.offer = false
  tour.index = 0
  tour.active = true
}

export function later() {
  tour.offer = false
  write(sessionStorage, LATER_KEY, '1')
}

export function finish(state: 'done' | 'skipped') {
  tour.active = false
  tour.offer = false
  write(localStorage, DONE_KEY, state)
}
