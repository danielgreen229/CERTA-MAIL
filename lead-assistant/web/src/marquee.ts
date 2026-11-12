import type { Directive } from 'vue'

/**
 * v-marquee: если текст не помещается, при наведении на строку он плавно прокручивается,
 * чтобы прочитать название целиком. Полный текст всегда доступен и в подсказке (title) —
 * в том числе при отключённой анимации в системе.
 */
type MarqueeEl = HTMLElement & { _marquee?: { host: HTMLElement; on: () => void; off: () => void } }

const reduced = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false

export const vMarquee: Directive<MarqueeEl> = {
  mounted(el) {
    const host = (el.closest('button, a, [data-marquee-host]') as HTMLElement | null) ?? el
    const on = () => {
      el.title = el.textContent?.trim() ?? ''
      const overflow = el.scrollWidth - el.clientWidth
      if (overflow <= 2 || reduced()) return
      el.style.setProperty('--marquee-shift', `${-overflow - 6}px`)
      // Скорость чтения ~45 px/с, не быстрее 1,6 с на проход.
      el.style.setProperty('--marquee-duration', `${Math.max(1.6, overflow / 45)}s`)
      el.classList.add('marquee-run')
    }
    const off = () => el.classList.remove('marquee-run')
    host.addEventListener('mouseenter', on)
    host.addEventListener('focus', on)
    host.addEventListener('mouseleave', off)
    host.addEventListener('blur', off)
    el._marquee = { host, on, off }
  },
  beforeUnmount(el) {
    const m = el._marquee
    if (!m) return
    m.host.removeEventListener('mouseenter', m.on)
    m.host.removeEventListener('focus', m.on)
    m.host.removeEventListener('mouseleave', m.off)
    m.host.removeEventListener('blur', m.off)
  },
}
