<script setup>
import { ref } from 'vue'

import { useAuth } from '../composables/useAuth'

const emit = defineEmits(['success'])
const { login } = useAuth()

const username = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)

async function submit() {
  if (!username.value.trim() || !password.value || loading.value) return
  loading.value = true
  error.value = ''
  try {
    await login(username.value.trim(), password.value)
    emit('success')
  } catch (e) {
    error.value = e.message || '登录失败'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login">
    <div class="card">
      <h2>登录 StarTrip</h2>
      <input v-model="username" placeholder="用户名" autocomplete="username" @keyup.enter="submit" />
      <input
        v-model="password"
        type="password"
        placeholder="密码"
        autocomplete="current-password"
        @keyup.enter="submit"
      />
      <p v-if="error" class="error">{{ error }}</p>
      <button :disabled="loading" @click="submit">{{ loading ? '登录中…' : '登录' }}</button>
    </div>
  </div>
</template>

<style scoped>
.login { display: flex; align-items: center; justify-content: center; height: 100%; width: 100%; }
.card { width: 280px; display: flex; flex-direction: column; gap: 10px; padding: 24px;
  border: 1px solid #eee; border-radius: 12px; box-shadow: 0 8px 24px rgba(0, 0, 0, 0.06); }
h2 { margin: 0 0 6px; font-size: 18px; }
input { padding: 9px 10px; border: 1px solid #ccc; border-radius: 6px; }
button { padding: 9px 12px; border: none; border-radius: 6px; background: #2c3e50; color: #fff; cursor: pointer; }
button:disabled { opacity: 0.6; cursor: default; }
.error { margin: 0; color: #c0392b; font-size: 13px; }
</style>
