<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, ApiError, type User } from '../api'
import BrandLogo from '../components/BrandLogo.vue'
import Icon from '../components/Icon.vue'
import { loadSession } from '../session'

const route = useRoute()
const router = useRouter()
const login = ref('')
const password = ref('')
const error = ref('')
const busy = ref(false)
const showPassword = ref(false)

async function submit() {
  error.value = ''
  busy.value = true
  try {
    await api.post<{ user: User }>('/api/auth/login', { login: login.value, password: password.value })
    await loadSession()
    router.push(String(route.query.next || '/leads'))
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось войти. Проверьте подключение к сети.'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="login">
    <aside class="brand" aria-hidden="true">
      <div class="brand-mark"><BrandLogo compact /></div>
      <p class="brand-line">Письма клиентов разобраны,<br />срочное — наверху.</p>
    </aside>
    <main class="side">
      <form class="form" @submit.prevent="submit">
        <div class="logo"><BrandLogo /></div>
        <h1>Вход в почту менеджера</h1>
        <p class="muted">Логин и пароль выдаёт администратор.</p>
        <label for="login">Логин</label>
        <div class="field">
          <Icon name="user" class="field-icon" />
          <input id="login" v-model="login" autocomplete="username" required autofocus />
        </div>
        <label for="password">Пароль</label>
        <div class="field">
          <Icon name="key" class="field-icon" />
          <input id="password" v-model="password" :type="showPassword ? 'text' : 'password'" autocomplete="current-password" required />
          <button type="button" class="ghost eye" :aria-label="showPassword ? 'Скрыть пароль' : 'Показать пароль'" @click="showPassword = !showPassword">
            {{ showPassword ? 'Скрыть' : 'Показать' }}
          </button>
        </div>
        <div v-if="error" class="alert error" role="alert"><Icon name="info" /> {{ error }}</div>
        <button class="primary submit" type="submit" :disabled="busy">
          <span v-if="busy" class="spinner"></span> Войти
        </button>
      </form>
    </main>
  </div>
</template>

<style scoped>
.login { min-height: 100vh; display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr); }
.brand {
  background: #25364f; color: #fff; display: flex; flex-direction: column; justify-content: flex-end;
  padding: 3rem 3.5rem; position: relative; overflow: hidden;
}
/* Знак-маршрут из логотипа, крупно и полупрозрачно — единственный декоративный жест. */
.brand-mark { position: absolute; right: -12%; top: 4%; height: 68%; opacity: 0.9; }
.brand-mark :deep(.mark) { fill: #af2a35; }
.brand-line { font-size: 2rem; line-height: 1.25; font-weight: 600; letter-spacing: -0.01em; margin: 0; max-width: 22ch; position: relative; }
.side { display: grid; place-items: center; padding: 2rem 1.25rem; background: var(--surface); }
.form { width: 100%; max-width: 24rem; }
.logo { height: 3rem; margin-bottom: 2rem; }
h1 { font-size: 1.55rem; margin-bottom: 0.35rem; }
.field { position: relative; display: flex; align-items: center; }
.field input { padding-left: 2.5rem; min-height: 2.9rem; }
.field-icon { position: absolute; left: 0.8rem; color: var(--muted); pointer-events: none; }
.eye { position: absolute; right: 0.25rem; min-height: 2.3rem; font-size: 0.85rem; color: var(--muted); }
.field input[type='password'], .field input[type='text']#password { padding-right: 5.5rem; }
.submit { width: 100%; margin-top: 1.25rem; min-height: 2.9rem; font-size: 1.02rem; }
@media (max-width: 900px) {
  .login { grid-template-columns: 1fr; }
  .brand { display: none; }
}
</style>
