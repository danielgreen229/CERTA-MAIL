<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, ROLE } from './api'
import { session, can } from './session'

const router = useRouter()
const menuOpen = ref(false)

async function logout() {
  await api.post('/api/auth/logout').catch(() => undefined)
  session.user = null
  router.push('/login')
}
</script>

<template>
  <header v-if="session.user" class="top">
    <div class="brand">Заявки «Церта»</div>
    <button class="menu-toggle" aria-label="Меню" @click="menuOpen = !menuOpen">☰</button>
    <nav :class="{ open: menuOpen }" @click="menuOpen = false">
      <RouterLink to="/leads">Заявки</RouterLink>
      <RouterLink to="/jobs">Обработка</RouterLink>
      <RouterLink v-if="can('supervisor')" to="/quality">Качество</RouterLink>
      <RouterLink to="/knowledge">База знаний</RouterLink>
      <RouterLink to="/connectors">Подключения</RouterLink>
      <RouterLink to="/settings">Настройки</RouterLink>
    </nav>
    <div class="who">
      <span class="small">{{ session.user.name }} · {{ ROLE[session.user.role] }}</span>
      <button @click="logout">Выйти</button>
    </div>
  </header>
  <div v-if="session.user && session.demoSettings" class="demo-bar">
    Демонстрационные настройки: сроки реакции, рабочий календарь и правила назначения — примерные.
    Измените их в «Настройках».
  </div>
  <RouterView />
</template>

<style scoped>
.top {
  display: flex; align-items: center; gap: 16px; padding: 8px 16px;
  background: var(--surface); border-bottom: 1px solid var(--line); position: sticky; top: 0; z-index: 5;
}
.brand { font-weight: 700; white-space: nowrap; }
nav { display: flex; gap: 4px; flex: 1; }
nav a { padding: 6px 10px; border-radius: 8px; text-decoration: none; color: var(--text); }
nav a.router-link-active { background: var(--accent-soft); color: var(--accent); }
.who { display: flex; align-items: center; gap: 8px; }
.menu-toggle { display: none; }
.demo-bar { background: var(--warn-soft); color: var(--warn); padding: 6px 16px; font-size: 13px; }
@media (max-width: 900px) {
  .top { flex-wrap: wrap; }
  .menu-toggle { display: inline-block; margin-left: auto; }
  nav { display: none; flex-basis: 100%; flex-direction: column; }
  nav.open { display: flex; }
  .who { flex-basis: 100%; justify-content: space-between; }
}
</style>
