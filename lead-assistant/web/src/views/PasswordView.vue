<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, ApiError } from '../api'
import { loadSession, session } from '../session'

const router = useRouter()
const old = ref('')
const next = ref('')
const repeat = ref('')
const error = ref('')
const busy = ref(false)

async function submit() {
  error.value = ''
  if (next.value !== repeat.value) {
    error.value = 'Новые пароли не совпадают'
    return
  }
  busy.value = true
  try {
    await api.post('/api/auth/password', { old: old.value, new: next.value })
    await loadSession()
    router.push('/leads')
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось сменить пароль'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="page" style="max-width: 420px">
    <form class="card" @submit.prevent="submit">
      <h1>Смена пароля</h1>
      <p v-if="session.user?.must_change_password" class="alert warn">
        Это первый вход: смените начальный пароль, чтобы продолжить.
      </p>
      <label for="old">Текущий пароль</label>
      <input id="old" v-model="old" type="password" autocomplete="current-password" required />
      <label for="new">Новый пароль (не короче 10 символов)</label>
      <input id="new" v-model="next" type="password" autocomplete="new-password" required minlength="10" />
      <label for="repeat">Новый пароль ещё раз</label>
      <input id="repeat" v-model="repeat" type="password" autocomplete="new-password" required />
      <div v-if="error" class="alert error">{{ error }}</div>
      <button class="primary" type="submit" :disabled="busy" style="margin-top: 12px">Сменить пароль</button>
    </form>
  </div>
</template>
