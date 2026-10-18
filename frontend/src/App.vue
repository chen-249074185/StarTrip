<script setup>
import { ref } from 'vue'

import ChatPanel from './components/ChatPanel.vue'
import { useSSE } from './composables/useSSE'

const messages = ref([])
const tripPlan = ref(null)
const score = ref(null)
const loading = ref(false)
const sessionId = 'web-' + Math.random().toString(36).slice(2, 8)
const { streamChat } = useSSE()

async function onSend(text) {
  messages.value.push({ role: 'user', text })
  loading.value = true
  tripPlan.value = null
  score.value = null
  const push = (t) => messages.value.push({ role: 'bot', text: t })

  try {
    await streamChat({
      sessionId,
      message: text,
      onEvent: (ev) => {
        if (ev.event === 'progress') push(ev.data.msg)
        else if (ev.event === 'result') {
          tripPlan.value = ev.data.trip_plan
          score.value = ev.data.score
        } else if (ev.event === 'error') push('出错: ' + (ev.data.msg || ''))
      },
    })
  } catch (e) {
    push('请求失败: ' + e.message)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="app">
    <header>StarTrip · 多 Agent 旅行规划</header>
    <main>
      <section class="left">
        <ChatPanel :messages="messages" :loading="loading" @send="onSend" />
      </section>
      <section class="right">
        <pre v-if="tripPlan">{{ JSON.stringify({ score, tripPlan }, null, 2) }}</pre>
        <p v-else class="hint">行程将显示在这里</p>
      </section>
    </main>
  </div>
</template>

<style>
* { box-sizing: border-box; }
body { margin: 0; font-family: system-ui, sans-serif; }
.app { display: flex; flex-direction: column; height: 100vh; }
header { padding: 12px 16px; background: #2c3e50; color: #fff; font-weight: 600; }
main { flex: 1; display: flex; min-height: 0; }
.left { width: 42%; border-right: 1px solid #eee; display: flex; flex-direction: column; }
.right { flex: 1; overflow: auto; padding: 12px; }
.right pre { white-space: pre-wrap; font-size: 12px; }
.hint { color: #999; }
</style>
