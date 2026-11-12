import { ref, watch } from 'vue'

/** Уведомления о новых письмах: звук (Web Audio, без файлов) и системное уведомление браузера. */
const STORAGE_KEY = 'leads.sound'

function storedSound(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) !== 'off'
  } catch {
    return true
  }
}

export const soundOn = ref(storedSound())
watch(soundOn, (on) => {
  try {
    localStorage.setItem(STORAGE_KEY, on ? 'on' : 'off')
  } catch {
    /* хранилище недоступно — настройка действует до перезагрузки */
  }
})

let audio: AudioContext | null = null

/** Короткий двухтоновый сигнал. Браузер разрешает звук после первого клика на странице. */
export function chime() {
  if (!soundOn.value) return
  try {
    audio ??= new AudioContext()
    const start = audio.currentTime + 0.02
    for (const [offset, frequency] of [[0, 880], [0.16, 1320]] as const) {
      const osc = audio.createOscillator()
      const gain = audio.createGain()
      osc.type = 'sine'
      osc.frequency.value = frequency
      gain.gain.setValueAtTime(0.0001, start + offset)
      gain.gain.exponentialRampToValueAtTime(0.18, start + offset + 0.02)
      gain.gain.exponentialRampToValueAtTime(0.0001, start + offset + 0.35)
      osc.connect(gain).connect(audio.destination)
      osc.start(start + offset)
      osc.stop(start + offset + 0.4)
    }
  } catch {
    /* звук недоступен — остаётся уведомление на странице */
  }
}

/** Включение звука заодно спрашивает разрешение на системные уведомления. */
export async function toggleSound() {
  soundOn.value = !soundOn.value
  if (soundOn.value) {
    chime()
    if ('Notification' in window && Notification.permission === 'default') {
      await Notification.requestPermission().catch(() => undefined)
    }
  }
}

export function systemNotice(title: string, body: string) {
  if (!('Notification' in window) || Notification.permission !== 'granted' || !document.hidden) return
  try {
    new Notification(title, { body, tag: 'leads-new-mail' })
  } catch {
    /* некоторые браузеры не дают создавать уведомления со страницы */
  }
}
