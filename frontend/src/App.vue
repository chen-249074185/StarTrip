<script setup>
import { onMounted, ref } from 'vue'

import ChatPanel from './components/ChatPanel.vue'
import LoginPanel from './components/LoginPanel.vue'
import TripDayCard from './components/TripDayCard.vue'
import TripMap from './components/TripMap.vue'
import { geocodeSpots, loadAmap } from './composables/useAmap'
import { useAuth } from './composables/useAuth'
import { useSSE } from './composables/useSSE'

const messages = ref([])
const tripPlan = ref(null)
const score = ref(null)
const options = ref([])
const pendingTasks = ref(null)
const loading = ref(false)
const authEnabled = ref(false)
const loggedIn = ref(true)
const amapKey = ref('')
const securityCode = ref('')
const spotCoords = ref({})
const savedSession = sessionStorage.getItem('startrip_session')
const sessionId = savedSession || 'web-' + Math.random().toString(36).slice(2, 8)
if (!savedSession) sessionStorage.setItem('startrip_session', sessionId)
const { token, logout } = useAuth()
const { streamChat, resumeChat } = useSSE()

onMounted(async () => {
  try {
    const r = await fetch('/api/config')
    const j = await r.json()
    amapKey.value = j.data?.amap_js_key || ''
    securityCode.value = j.data?.amap_js_security_code || ''
    authEnabled.value = !!j.data?.auth_enabled
    if (authEnabled.value) {
      if (!token.value) {
        loggedIn.value = false
      } else {
        const me = await fetch('/api/auth/me', {
          headers: { Authorization: `Bearer ${token.value}` },
        })
        if (!me.ok) {
          logout()
          loggedIn.value = false
        }
      }
    }
  } catch {
    // 拿不到配置也不影响对话
  }
})

function onLogout() {
  logout()
  loggedIn.value = false
  messages.value = []
  tripPlan.value = null
  score.value = null
  options.value = []
  pendingTasks.value = null
  spotCoords.value = {}
}

function handleUnauthorized() {
  logout()
  loggedIn.value = false
  push('登录已过期，请重新登录')
}

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

const push = (t) => messages.value.push({ role: 'bot', text: t })

function handleEvent(ev) {
  if (ev.event === 'progress') push(ev.data.msg)
  else if (ev.event === 'node') messages.value.push({ role: 'detail', text: ev.data.msg })
  else if (ev.event === 'interrupt') {
    pendingTasks.value = ev.data.tasks || []
    push(ev.data.msg || '请确认任务清单')
  } else if (ev.event === 'result') {
    pendingTasks.value = null
    tripPlan.value = ev.data.trip_plan
    score.value = ev.data.score
    if (ev.data.reply) push(ev.data.reply)
    options.value = ev.data.options || []
    if (tripPlan.value) resolveCoords()
  } else if (ev.event === 'error') push('出错: ' + (ev.data.msg || ''))
}

async function onSend(text) {
  messages.value.push({ role: 'user', text })
  loading.value = true
  pendingTasks.value = null
  tripPlan.value = null
  score.value = null
  options.value = []
  spotCoords.value = {}

  try {
    await streamChat({ sessionId, message: text, token: token.value, onEvent: handleEvent })
  } catch (e) {
    if (e.status === 401) handleUnauthorized()
    else push('请求失败: ' + e.message)
  } finally {
    loading.value = false
  }
}

async function onResume(tasks) {
  if (loading.value) return
  loading.value = true
  try {
    await resumeChat({ sessionId, tasks, token: token.value, onEvent: handleEvent })
  } catch (e) {
    if (e.status === 401) handleUnauthorized()
    else push('请求失败: ' + e.message)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="app">
    <header>
      <span>StarTrip · 多 Agent 旅行规划</span>
      <button v-if="authEnabled && loggedIn" class="logout" @click="onLogout">退出</button>
    </header>
    <main v-if="!authEnabled || loggedIn">
      <section class="left">
        <ChatPanel
          :messages="messages"
          :loading="loading"
          :options="options"
          :tasks="pendingTasks"
          @send="onSend"
          @resume="onResume"
        />
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
    <main v-else>
      <LoginPanel @success="loggedIn = true" />
    </main>
  </div>
</template>

<style>
* { box-sizing: border-box; }
body { margin: 0; font-family: system-ui, sans-serif; }
.app { display: flex; flex-direction: column; height: 100vh; }
header { display: flex; align-items: center; justify-content: space-between;
  padding: 12px 16px; background: #2c3e50; color: #fff; font-weight: 600; }
.logout { padding: 5px 10px; border: 1px solid rgba(255, 255, 255, 0.5); background: transparent;
  color: #fff; border-radius: 6px; cursor: pointer; font-size: 12px; }
main { flex: 1; display: flex; min-height: 0; }
.left { width: 40%; border-right: 1px solid #eee; display: flex; flex-direction: column; }
.right { flex: 1; overflow: auto; padding: 16px; }
.hint { color: #999; }
</style>
