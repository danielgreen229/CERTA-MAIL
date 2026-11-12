<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, ApiError, type User } from '../api'
import { loadSession } from '../session'

const route = useRoute()
const router = useRouter()
const login = ref('')
const password = ref('')
const error = ref('')
const busy = ref(false)

async function submit() {
  error.value = ''
  busy.value = true
  try {
    await api.post<{ user: User }>('/api/auth/login', { login: login.value, password: password.value })
    await loadSession()
    router.push(String(route.query.next || '/leads'))
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось войти'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <main class="login">
    <form class="card" @submit.prevent="submit">
      <h1>Вход</h1>
      <p class="muted small">Рабочее место менеджера по заявкам</p>
      <label for="login">Логин</label>
      <input id="login" v-model="login" autocomplete="username" required />
      <label for="password">Пароль</label>
      <input id="password" v-model="password" type="password" autocomplete="current-password" required />
      <div v-if="error" class="alert error">{{ error }}</div>
      <button class="primary" type="submit" :disabled="busy" style="margin-top: 12px; width: 100%">
        <span v-if="busy" class="spinner"></span> Войти
      </button>
    </form>
  </main>
</template>

<style scoped>
.login { min-height: 100vh; display: grid; place-items: center; padding: 16px; }
form { width: 100%; max-width: 360px; }
</style>
