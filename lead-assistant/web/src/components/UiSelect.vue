<script setup lang="ts">
/**
 * Выпадающий список Certa вместо системного <select>: одинаковый вид во всех браузерах
 * и темах, группы, цветные метки, полная работа с клавиатуры (стрелки, Enter, Esc, буквы).
 */
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import Icon from './Icon.vue'

export interface SelectOption {
  value: string
  label: string
  group?: string
  hint?: string
  /** Цветная точка слева: high / medium / low. */
  tone?: string
}

const props = withDefaults(
  defineProps<{ modelValue: string; options: SelectOption[]; placeholder?: string; ariaLabel?: string; id?: string }>(),
  { placeholder: 'Выберите', ariaLabel: undefined, id: undefined },
)
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

const open = ref(false)
const active = ref(0)
const root = ref<HTMLElement | null>(null)
const list = ref<HTMLElement | null>(null)
const uid = `ui-select-${Math.random().toString(36).slice(2, 9)}`

const selected = computed(() => props.options.find((o) => o.value === props.modelValue) ?? null)
const groups = computed(() => {
  const out: Array<{ name: string; items: Array<SelectOption & { index: number }> }> = []
  props.options.forEach((option, index) => {
    const name = option.group ?? ''
    let group = out.find((g) => g.name === name)
    if (!group) out.push((group = { name, items: [] }))
    group.items.push({ ...option, index })
  })
  return out
})

function show() {
  open.value = true
  active.value = Math.max(0, props.options.findIndex((o) => o.value === props.modelValue))
  nextTick(scrollActive)
}
function hide() {
  open.value = false
}
function choose(index: number) {
  const option = props.options[index]
  if (option) emit('update:modelValue', option.value)
  hide()
  root.value?.querySelector<HTMLButtonElement>('.trigger')?.focus()
}
function scrollActive() {
  list.value?.querySelector<HTMLElement>(`[data-index="${active.value}"]`)?.scrollIntoView({ block: 'nearest' })
}
function move(step: number) {
  if (!open.value) return show()
  const count = props.options.length
  active.value = (active.value + step + count) % count
  nextTick(scrollActive)
}
function onKey(event: KeyboardEvent) {
  if (event.key === 'ArrowDown') { event.preventDefault(); move(1) }
  else if (event.key === 'ArrowUp') { event.preventDefault(); move(-1) }
  else if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    if (open.value) choose(active.value)
    else show()
  } else if (event.key === 'Escape' && open.value) { event.preventDefault(); event.stopPropagation(); hide() }
  else if (event.key === 'Tab') hide()
  else if (event.key.length === 1) {
    // Переход к пункту по первой букве.
    const letter = event.key.toLowerCase()
    const start = open.value ? active.value + 1 : 0
    const order = [...props.options.keys()].map((i) => (i + start) % props.options.length)
    const found = order.find((i) => props.options[i]?.label.toLowerCase().startsWith(letter))
    if (found !== undefined) {
      if (!open.value) show()
      active.value = found
      nextTick(scrollActive)
    }
  }
}
function onOutside(event: MouseEvent) {
  if (root.value && !root.value.contains(event.target as Node)) hide()
}
watch(open, (value) => {
  if (value) document.addEventListener('mousedown', onOutside)
  else document.removeEventListener('mousedown', onOutside)
})
onBeforeUnmount(() => document.removeEventListener('mousedown', onOutside))
</script>

<template>
  <div ref="root" class="ui-select" :class="{ open }">
    <button
      :id="id"
      type="button"
      class="trigger"
      role="combobox"
      :aria-label="ariaLabel"
      :aria-expanded="open"
      :aria-controls="uid"
      aria-haspopup="listbox"
      :aria-activedescendant="open ? `${uid}-${active}` : undefined"
      @click="open ? hide() : show()"
      @keydown="onKey"
    >
      <span v-if="selected?.tone" class="dot" :class="selected.tone" aria-hidden="true"></span>
      <span class="value" :class="{ placeholder: !selected }">{{ selected?.label ?? placeholder }}</span>
      <Icon name="chevron" class="chev" size="1rem" />
    </button>
    <div v-if="open" :id="uid" ref="list" class="pop" role="listbox" :aria-label="ariaLabel">
      <template v-for="group in groups" :key="group.name">
        <div v-if="group.name" class="group" role="presentation">{{ group.name }}</div>
        <div
          v-for="item in group.items"
          :id="`${uid}-${item.index}`"
          :key="item.value + item.index"
          :data-index="item.index"
          class="option"
          role="option"
          :aria-selected="item.value === modelValue"
          :class="{ active: item.index === active, chosen: item.value === modelValue }"
          @mousemove="active = item.index"
          @mousedown.prevent="choose(item.index)"
        >
          <span v-if="item.tone" class="dot" :class="item.tone" aria-hidden="true"></span>
          <span class="label">
            {{ item.label }}
            <span v-if="item.hint" class="hint">{{ item.hint }}</span>
          </span>
          <Icon v-if="item.value === modelValue" name="check" size="1rem" class="tick" />
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.ui-select { position: relative; min-width: 0; }
.trigger {
  width: 100%; justify-content: flex-start; gap: 0.5rem; font-weight: 450; padding: 0.45rem 0.7rem;
  background: var(--surface); text-align: left;
}
.open .trigger { border-color: var(--accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent); }
.value { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.placeholder { color: var(--muted); }
.chev { color: var(--muted); transition: transform 0.15s ease; }
.open .chev { transform: rotate(180deg); }
.pop {
  position: absolute; z-index: 70; left: 0; top: calc(100% + 0.3rem); min-width: 100%; width: max-content;
  max-width: min(26rem, 90vw); max-height: 18rem; overflow-y: auto; padding: 0.3rem;
  background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius);
  box-shadow: var(--shadow-pop); scrollbar-width: thin;
}
.group { padding: 0.45rem 0.6rem 0.2rem; font-size: 0.8rem; font-weight: 600; color: var(--muted); }
.option {
  display: flex; align-items: center; gap: 0.55rem; padding: 0.5rem 0.6rem; border-radius: var(--radius-s);
  cursor: pointer; color: var(--text);
}
.option.active { background: var(--accent-soft); }
.option.chosen { font-weight: 600; color: var(--accent); }
.label { flex: 1; min-width: 0; }
.hint { display: block; font-size: 0.8rem; color: var(--muted); font-weight: 400; }
.tick { color: var(--accent); }
.dot { width: 0.6rem; height: 0.6rem; border-radius: 50%; flex: none; background: var(--line-strong); }
.dot.high { background: var(--brand-red); }
.dot.medium { background: #d99a1e; }
.dot.low { background: var(--ok); }
@media (prefers-reduced-motion: reduce) { .chev { transition: none; } }
</style>
