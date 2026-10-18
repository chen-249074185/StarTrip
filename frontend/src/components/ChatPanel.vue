<script setup>
import { ref } from 'vue'

const props = defineProps({
  messages: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
})
const emit = defineEmits(['send'])
const input = ref('')

function submit() {
  const text = input.value.trim()
  if (!text || props.loading) return
  emit('send', text)
  input.value = ''
}
</script>

<template>
  <div class="chat">
    <div class="msgs">
      <div v-for="(m, i) in messages" :key="i" :class="['msg', m.role]">{{ m.text }}</div>
    </div>
    <div class="input">
      <input
        v-model="input"
        placeholder="描述你的出行需求，例如：上海两日游，预算1000，不爱走路"
        @keyup.enter="submit"
      />
      <button :disabled="loading" @click="submit">{{ loading ? '规划中…' : '发送' }}</button>
    </div>
  </div>
</template>

<style scoped>
.chat { display: flex; flex-direction: column; height: 100%; }
.msgs { flex: 1; overflow-y: auto; padding: 10px; }
.msg { margin: 6px 0; padding: 8px 10px; border-radius: 8px; max-width: 82%; white-space: pre-wrap; }
.msg.user { background: #d6e4ff; margin-left: auto; }
.msg.bot { background: #f0f0f0; }
.input { display: flex; gap: 8px; padding: 10px; border-top: 1px solid #eee; }
.input input { flex: 1; padding: 8px; border: 1px solid #ccc; border-radius: 6px; }
.input button { padding: 8px 14px; border: none; background: #2c3e50; color: #fff; border-radius: 6px; cursor: pointer; }
.input button:disabled { opacity: 0.6; cursor: default; }
</style>
