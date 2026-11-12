<script setup lang="ts">
import { computed, reactive } from 'vue'
import { PRIORITY } from '../api'
import { isFolderActive, mail, type FolderFilter, type SourceTab } from '../mailbox'
import Icon, { type IconName } from './Icon.vue'

/** Папки «Почты» в боковом меню: ящики со срочностью, письма в работе, решённые. */
interface Folder {
  id: string
  label: string
  icon: IconName
  tone?: 'high' | 'medium' | 'low'
  filter: FolderFilter
  count: number
  total?: number
  /** Счётчик требует внимания — красная плашка. */
  attention?: boolean
  children?: Folder[]
}

const emit = defineEmits<{ select: [filter: FolderFilter] }>()

const STORAGE_KEY = 'leads.folders.collapsed'
function loadCollapsed(): Record<string, boolean> {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '{}') as Record<string, boolean>
  } catch {
    return {}
  }
}
const collapsed = reactive<Record<string, boolean>>(loadCollapsed())
function toggle(id: string) {
  collapsed[id] = !collapsed[id]
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(collapsed))
  } catch {
    /* состояние живёт до перезагрузки */
  }
}

const f = (key: string) => mail.data?.folders[key] ?? 0
const counts = computed(() => mail.data?.counts ?? {})
const sourceIcon = (tab: SourceTab): IconName =>
  tab.key === 'telegram' || tab.key.startsWith('@') ? 'telegram' : tab.mailbox || tab.key === 'email' ? 'mail' : 'inbox'
const TONE = { high: 'high', medium: 'medium', low: 'low' } as const

const groups = computed(() => [
  {
    id: 'inbox',
    title: 'Входящие',
    folders: [
      {
        id: 'all',
        label: 'Все письма',
        icon: 'inbox' as IconName,
        filter: {},
        count: (counts.value.new ?? 0) + (counts.value.pending ?? 0),
        total: counts.value.total ?? 0,
      },
      ...(mail.data?.sources ?? []).map(
        (tab): Folder => ({
          id: `source:${tab.key}`,
          label: tab.title,
          icon: sourceIcon(tab),
          filter: { source: tab.key },
          count: tab.open,
          total: tab.count,
          children: (['high', 'medium', 'low'] as const).map((priority) => ({
            id: `source:${tab.key}|priority:${priority}`,
            label: PRIORITY[priority] ?? priority,
            icon: 'flag' as IconName,
            tone: TONE[priority],
            filter: { source: tab.key, priority },
            count: f(`open:source:${tab.key}|priority:${priority}`),
            total: f(`source:${tab.key}|priority:${priority}`),
            attention: priority === 'high',
          })),
        }),
      ),
    ] as Folder[],
  },
  {
    id: 'work',
    title: 'В работе',
    folders: [
      { id: 'pending', label: 'Ждут решения', icon: 'decide', filter: { state: 'pending' }, count: f('state:pending') },
      { id: 'review', label: 'На проверку', icon: 'flag', filter: { review: '1' }, count: counts.value.needs_review ?? 0 },
      { id: 'high', label: 'Срочные', icon: 'flame', filter: { priority: 'high' }, count: counts.value.high ?? 0, attention: true },
      { id: 'overdue', label: 'Просрочены', icon: 'alarm', filter: { overdue: '1' }, count: counts.value.overdue ?? 0, attention: true },
      { id: 'new', label: 'Ещё не разобраны', icon: 'hourglass', filter: { state: 'new' }, count: f('state:new') },
    ] as Folder[],
  },
  {
    id: 'done',
    title: 'Решённые',
    folders: [
      { id: 'accepted', label: 'Приняты', icon: 'check', filter: { state: 'accepted' }, count: f('state:accepted') },
      { id: 'corrected', label: 'Исправлены', icon: 'edit', filter: { state: 'corrected' }, count: f('state:corrected') },
      { id: 'rejected', label: 'Отклонены', icon: 'reject', filter: { state: 'rejected' }, count: f('state:rejected') },
    ] as Folder[],
  },
])

function hint(folder: Folder): string {
  if (folder.total === undefined) return `${folder.label}: ${folder.count}`
  return `${folder.label}: ждут ответа — ${folder.count}, всего — ${folder.total}`
}
</script>

<template>
  <div class="folders">
    <section v-for="group in groups" :key="group.id" class="group">
      <button
        class="group-head"
        type="button"
        :aria-expanded="!collapsed[group.id]"
        :aria-controls="`folders-${group.id}`"
        @click="toggle(group.id)"
      >
        {{ group.title }}
        <Icon name="chevron" class="chev" :class="{ closed: collapsed[group.id] }" size="0.95rem" />
      </button>
      <ul v-show="!collapsed[group.id]" :id="`folders-${group.id}`">
        <li v-for="folder in group.folders" :key="folder.id">
          <div class="line">
            <button
              type="button"
              class="folder"
              :class="{ active: isFolderActive(folder.filter) }"
              :aria-current="isFolderActive(folder.filter) ? 'page' : undefined"
              :title="hint(folder)"
              @click="emit('select', folder.filter)"
            >
              <Icon :name="folder.icon" size="1.1rem" />
              <span v-marquee class="label">{{ folder.label }}</span>
              <span v-if="folder.count" class="count num" :class="{ attention: folder.attention }">{{ folder.count }}</span>
            </button>
            <button
              v-if="folder.children"
              type="button"
              class="expander"
              :aria-expanded="!collapsed[folder.id]"
              :aria-label="`${collapsed[folder.id] ? 'Показать' : 'Скрыть'} срочность: ${folder.label}`"
              @click="toggle(folder.id)"
            >
              <Icon name="chevron" class="chev" :class="{ closed: collapsed[folder.id] }" size="0.95rem" />
            </button>
          </div>
          <ul v-if="folder.children" v-show="!collapsed[folder.id]" class="children">
            <li v-for="child in folder.children" :key="child.id">
              <button
                type="button"
                class="folder child"
                :class="{ active: isFolderActive(child.filter) }"
                :title="hint(child)"
                @click="emit('select', child.filter)"
              >
                <span class="dot" :class="child.tone" aria-hidden="true"></span>
                <span v-marquee class="label">{{ child.label }}</span>
                <span v-if="child.count" class="count num" :class="{ attention: child.attention }">{{ child.count }}</span>
              </button>
            </li>
          </ul>
        </li>
      </ul>
    </section>
  </div>
</template>

<style scoped>
.folders { display: flex; flex-direction: column; gap: 0.35rem; }
.group-head {
  width: 100%; justify-content: space-between; border: 0; background: none; min-height: 0;
  padding: 0.45rem 0.6rem 0.3rem; font-size: 0.82rem; font-weight: 560; color: var(--muted);
}
.group-head:hover:not(:disabled) { background: none; color: var(--text); }
.chev { transition: transform 0.15s ease; }
.chev.closed { transform: rotate(-90deg); }
ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 1px; }
.line { display: flex; align-items: center; }
.folder {
  flex: 1; min-width: 0; justify-content: flex-start; gap: 0.6rem; border: 0; background: none;
  border-radius: var(--radius-s); padding: 0.4rem 0.6rem; min-height: 2.25rem;
  color: var(--text); font-weight: 450; text-align: left;
}
.folder:hover:not(:disabled) { background: var(--accent-soft); border: 0; }
.folder.active { background: var(--accent-soft); color: var(--accent); font-weight: 600; }
.folder :deep(.icon) { color: var(--muted); }
.folder.active :deep(.icon) { color: var(--accent); }
.expander {
  border: 0; background: none; min-height: 0; width: 1.9rem; height: 2rem; padding: 0;
  color: var(--muted); flex: none;
}
.expander:hover:not(:disabled) { background: var(--accent-soft); border: 0; }
.children { padding-left: 1.55rem; margin-bottom: 0.2rem; }
.folder.child { min-height: 2rem; font-size: 0.92rem; }
.label { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.count { font-size: 0.8rem; color: var(--muted); font-weight: 600; }
.count.attention {
  color: #fff; background: var(--brand-red); border-radius: 99px; padding: 0 0.45rem; line-height: 1.45rem;
  min-width: 1.45rem; text-align: center;
}
.dot { width: 0.55rem; height: 0.55rem; border-radius: 50%; flex: none; margin: 0 0.3rem 0 0.25rem; }
.dot.high { background: var(--brand-red); }
.dot.medium { background: #d99a1e; }
.dot.low { background: var(--ok); }
@media (prefers-reduced-motion: reduce) { .chev { transition: none; } }
</style>
