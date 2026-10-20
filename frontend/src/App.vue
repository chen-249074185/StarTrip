<script setup>
import { onMounted, ref } from 'vue'

import ChatPanel from './components/ChatPanel.vue'
import TripDayCard from './components/TripDayCard.vue'
import TripMap from './components/TripMap.vue'
import { geocodeSpots, loadAmap } from './composables/useAmap'
import { useSSE } from './composables/useSSE'

const messages = ref([])
const tripPlan = ref(null)
const score = ref(null)
const options = ref([])
const loading = ref(false)
const amapKey = ref('')
const securityCode = ref('')
const spotCoords = ref({})
const savedSession = sessionStorage.getItem('startrip_session')
const sessionId = savedSession || 'web-' + Math.random().toString(36).slice(2, 8)
if (!savedSession) sessionStorage.setItem('startrip_session', sessionId)
const { streamChat } = useSSE()

onMounted(async () => {
  try {
    const r = await fetch('/api/config')
    const j = await r.json()
    amapKey.value = j.data?.amap_js_key || ''
    securityCode.value = j.data?.amap_js_security_code || ''
  } catch {
    // 拿不到配置也不影响对话
  }
})

async function resolveCoords() {
  spotCoords.value = {}
  if (!amapKey.value || !tripPlan.value) return
  try {
    const AMap = await loadAmap(amapKey.value, securityCode.value)
    const names = []
    for (const day of tripPlan.value.days || []) {
      for (const s of day.spots || []) names.push(s.name)
    }
    spotCoords.value = await geocodeSpots(AMap, names, '')
  } catch {
    // 地图不可用时，卡片仍可用（只是没有导航链接）
  }
}

async function onSend(text) {
  messages.value.push({ role: 'user', text })
  loading.value = true
  tripPlan.value = null
  score.value = null
  options.value = []
  spotCoords.value = {}
  const push = (t) => messages.value.push({ role: 'bot', text: t })

  try {
    await streamChat({
      sessionId,
      message: text,
      onEvent: (ev) => {
        if (ev.event === 'progress') push(ev.data.msg)
        else if (ev.event === 'node') messages.value.push({ role: 'detail', text: ev.data.msg })
        else if (ev.event === 'result') {
          tripPlan.value = ev.data.trip_plan
          score.value = ev.data.score
          if (ev.data.reply) push(ev.data.reply)
          options.value = ev.data.options || []
          if (tripPlan.value) resolveCoords()
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
        <ChatPanel :messages="messages" :loading="loading" :options="options" @send="onSend" />
      </section>
      <section class="right">
        <template v-if="tripPlan">
          <TripDayCard :plan="tripPlan" :score="score" :spot-coords="spotCoords" />
          <TripMap
            :plan="tripPlan"
            :spot-coords="spotCoords"
            :amap-key="amapKey"
            :security-code="securityCode"
          />
        </template>
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
.left { width: 40%; border-right: 1px solid #eee; display: flex; flex-direction: column; }
.right { flex: 1; overflow: auto; padding: 16px; }
.hint { color: #999; }
</style>
