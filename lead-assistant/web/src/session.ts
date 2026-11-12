import { reactive } from 'vue'
import { api, type User } from './api'

export const session = reactive<{ user: User | null; loaded: boolean; demoSettings: boolean; version: string }>({
  user: null,
  loaded: false,
  demoSettings: false,
  version: '',
})

export async function loadSession(): Promise<void> {
  try {
    const data = await api.get<{ user: User; demo_settings: boolean; version: string }>('/api/auth/me')
    session.user = data.user
    session.demoSettings = data.demo_settings
    session.version = data.version
  } catch {
    session.user = null
  }
  session.loaded = true
}

export function can(role: 'manager' | 'supervisor' | 'admin'): boolean {
  const rank = { manager: 0, supervisor: 1, admin: 2 }
  return !!session.user && rank[session.user.role] >= rank[role]
}
