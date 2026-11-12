<script setup lang="ts">
import { computed, reactive } from 'vue'
import { CATEGORY } from '../api'

export interface SourceTab {
  key: string
  title: string
  mailbox: boolean
  count: number
  open: number
}

export type FolderFilter = Partial<Record<'category' | 'priority' | 'state' | 'review' | 'source' | 'overdue', string>>

interface Folder {
  id: string
  label: string
  icon: string
  filter: FolderFilter
  count: number
  /** Счётчик требует внимания — выделяется цветом. */
  attention?: boolean
}

interface Group {
  id: string
  title: string
  folders: Folder[]
}

const props = defineProps<{
  counts: Record<string, number>
  folders: Record<string, number>
  sources: SourceTab[]
  current: FolderFilter
}>()
const emit = defineEmits<{ select: [filter: FolderFilter] }>()

const KEYS = ['category', 'priority', 'state', 'review', 'source', 'overdue'] as const
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
    /* хранилище недоступно — состояние живёт до перезагрузки */
  }
}

const sourceIcon = (tab: SourceTab) => (tab.mailbox || tab.key === 'email' ? '✉' : tab.key === 'telegram' ? '✈' : '•')
const f = (key: string) => props.folders[key] ?? 0

const groups = computed<Group[]>(() => [
  {
    id: 'inbox',
    title: 'Входящие',
    folders: [
      { id: 'all', label: 'Все заявки', icon: '📥', filter: {}, count: props.counts.total ?? 0 },
      ...props.sources.map((tab) => ({
        id: `source:${tab.key}`,
        label: tab.title,
        icon: sourceIcon(tab),
        filter: { source: tab.key },
        count: tab.open || tab.count,
        attention: tab.open > 0,
      })),
    ],
  },
  {
    id: 'work',
    title: 'В работе',
    folders: [
      { id: 'new', label: 'Ждут агента', icon: '⏳', filter: { state: 'new' }, count: f('state:new'), attention: f('state:new') > 0 },
      { id: 'pending', label: 'Ждут решения', icon: '📝', filter: { state: 'pending' }, count: f('state:pending'), attention: f('state:pending') > 0 },
      { id: 'review', label: 'На проверку', icon: '⚑', filter: { review: '1' }, count: props.counts.needs_review ?? 0, attention: (props.counts.needs_review ?? 0) > 0 },
      { id: 'high', label: 'Срочные', icon: '🔥', filter: { priority: 'high' }, count: props.counts.high ?? 0 },
      { id: 'overdue', label: 'Просрочены', icon: '⏰', filter: { overdue: '1' }, count: props.counts.overdue ?? 0, attention: (props.counts.overdue ?? 0) > 0 },
    ],
  },
  {
    id: 'category',
    title: 'Категории',
    folders: (Object.entries(CATEGORY) as [string, string][]).map(([key, title]) => ({
      id: `category:${key}`,
      label: title,
      icon: { sale: '💼', complaint: '⚠', question: '❓', spam: '🚫' }[key] ?? '•',
      filter: { category: key },
      count: f(`category:${key}`),
    })),
  },
  {
    id: 'done',
    title: 'Решённые',
    folders: [
      { id: 'accepted', label: 'Приняты', icon: '✓', filter: { state: 'accepted' }, count: f('state:accepted') },
      { id: 'corrected', label: 'Исправлены', icon: '✎', filter: { state: 'corrected' }, count: f('state:corrected') },
      { id: 'rejected', label: 'Отклонены', icon: '✕', filter: { state: 'rejected' }, count: f('state:rejected') },
    ],
  },
])

/** Папка активна, если текущие фильтры совпадают с её фильтром полностью. */
function isActive(folder: Folder): boolean {
  return KEYS.every((key) => (props.current[key] ?? '') === (folder.filter[key] ?? ''))
}
</script>

<template>
  <nav class="folders" aria-label="Папки заявок">
    <section v-for="group in groups" :key="group.id" class="group">
      <button
        class="group-head"
        type="button"
        :aria-expanded="!collapsed[group.id]"
        :aria-controls="`folders-${group.id}`"
        @click="toggle(group.id)"
      >
        <span class="chevron" :class="{ closed: collapsed[group.id] }" aria-hidden="true">▾</span>
        {{ group.title }}
      </button>
      <ul v-show="!collapsed[group.id]" :id="`folders-${group.id}`">
        <li v-for="folder in group.folders" :key="folder.id">
          <button
            type="button"
            class="folder"
            :class="{ active: isActive(folder) }"
            :aria-current="isActive(folder) ? 'page' : undefined"
            @click="emit('select', folder.filter)"
          >
            <span class="icon" aria-hidden="true">{{ folder.icon }}</span>
            <span class="label" :title="folder.label">{{ folder.label }}</span>
            <span v-if="folder.count" class="count" :class="{ attention: folder.attention }">{{ folder.count }}</span>
          </button>
        </li>
      </ul>
    </section>
  </nav>
</template>

<style scoped>
.folders { display: flex; flex-direction: column; gap: 6px; font-size: 14px; }
.group-head {
  width: 100%; display: flex; align-items: center; gap: 6px; border: 0; background: none;
  padding: 6px 8px; min-height: 0; font-size: 12px; font-weight: 600; text-transform: uppercase;
  letter-spacing: 0.04em; color: var(--muted); cursor: pointer; text-align: left;
}
.group-head:hover { color: var(--text); }
.chevron { display: inline-block; transition: transform 0.15s ease; width: 12px; }
.chevron.closed { transform: rotate(-90deg); }
ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 1px; }
.folder {
  width: 100%; display: flex; align-items: center; gap: 8px; border: 0; border-radius: 8px;
  background: none; padding: 6px 8px 6px 14px; min-height: 34px; color: var(--text);
  text-align: left; cursor: pointer; font-size: 14px;
}
.folder:hover { background: var(--accent-soft); }
.folder.active { background: var(--accent-soft); color: var(--accent); font-weight: 600; }
.icon { width: 18px; text-align: center; flex: none; }
.label { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.count { font-size: 12px; color: var(--muted); font-variant-numeric: tabular-nums; }
.count.attention { color: #fff; background: var(--accent); border-radius: 10px; padding: 0 7px; font-weight: 600; }
@media (prefers-reduced-motion: reduce) { .chevron { transition: none; } }
</style>
