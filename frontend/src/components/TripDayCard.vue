<script setup>
const props = defineProps({
  plan: { type: Object, default: null },
  score: { type: Number, default: null },
  spotCoords: { type: Object, default: () => ({}) },
})

// 高德 URI 导航：from 缺省用当前定位，点击在 App/浏览器打开导航
function navUrl(name) {
  const c = props.spotCoords[name]
  if (!c) return ''
  const to = `${c[0]},${c[1]},${encodeURIComponent(name)}`
  return `https://uri.amap.com/navigation?to=${to}&mode=car&policy=1&src=startrip&coordinate=gaode&callnative=0`
}
</script>

<template>
  <div v-if="plan" class="cards">
    <div v-if="score !== null" class="score">综合评分：{{ score }}</div>
    <div v-for="day in plan.days" :key="day.date" class="day">
      <div class="day-head">
        <span class="date">{{ day.date }}</span>
        <span class="budget">预算 ¥{{ day.budget_total }}</span>
      </div>
      <ul class="spots">
        <li v-for="(s, i) in day.spots" :key="i" class="spot">
          <div class="spot-head">
            <span class="name">{{ s.name }}</span>
            <span class="time">{{ s.time }}</span>
          </div>
          <div class="meta">
            <span v-if="s.transport" class="transport">{{ s.transport }}</span>
            <span v-if="s.budget" class="cost">¥{{ s.budget }}</span>
            <a
              v-if="navUrl(s.name)"
              class="nav"
              :href="navUrl(s.name)"
              target="_blank"
              rel="noopener"
              >导航前往</a
            >
          </div>
          <div v-if="s.note" class="note">{{ s.note }}</div>
        </li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.cards { display: flex; flex-direction: column; gap: 14px; }
.score { font-weight: 700; color: #2c3e50; }
.day { border: 1px solid #e6e6e6; border-radius: 10px; overflow: hidden; }
.day-head { display: flex; justify-content: space-between; padding: 8px 12px; background: #2c3e50; color: #fff; }
.spots { list-style: none; margin: 0; padding: 0; }
.spot { padding: 10px 12px; border-top: 1px solid #f0f0f0; }
.spot-head { display: flex; justify-content: space-between; align-items: baseline; }
.name { font-weight: 600; }
.time { color: #888; font-size: 12px; }
.meta { display: flex; gap: 12px; align-items: center; color: #666; font-size: 12px; margin-top: 2px; }
.nav { margin-left: auto; color: #2c3e50; font-weight: 600; text-decoration: none; }
.nav:hover { text-decoration: underline; }
.note { color: #555; font-size: 13px; margin-top: 4px; }
</style>
