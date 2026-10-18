<script setup>
import { onMounted, onUnmounted, ref, watch } from 'vue'

import { loadAmap } from '../composables/useAmap'

const props = defineProps({
  plan: { type: Object, default: null },
  spotCoords: { type: Object, default: () => ({}) },
  amapKey: { type: String, default: '' },
  securityCode: { type: String, default: '' },
})

const mapEl = ref(null)
const status = ref('') // '' | 'loading' | 'ok' | 'nokey' | 'error'
const errorMsg = ref('')
let map = null

function drawRoute(AMap, pts) {
  const start = new AMap.LngLat(pts[0][0], pts[0][1])
  const end = new AMap.LngLat(pts[pts.length - 1][0], pts[pts.length - 1][1])
  const waypoints = pts.slice(1, -1).map((p) => new AMap.LngLat(p[0], p[1]))
  const driving = new AMap.Driving({ policy: AMap.DrivingPolicy.LEAST_TIME })
  driving.search(start, end, { waypoints }, (st, res) => {
    if (st !== 'complete' || !res?.routes?.length) return
    const path = []
    for (const step of res.routes[0].steps) {
      for (const p of step.path) path.push([p.lng, p.lat])
    }
    new AMap.Polyline({ path, map, strokeColor: '#2c3e50', strokeWeight: 4, strokeOpacity: 0.8 })
  })
}

async function render() {
  if (!props.plan) return
  if (!props.amapKey) {
    status.value = 'nokey'
    return
  }
  const coords = props.spotCoords || {}
  if (!Object.keys(coords).length) return // 坐标未就绪，等 watch 触发

  status.value = 'loading'
  try {
    const AMap = await loadAmap(props.amapKey, props.securityCode)
    if (!map) {
      map = new AMap.Map(mapEl.value, {
        zoom: 11,
        center: [121.49, 31.24],
        mapStyle: 'amap://styles/whitesmoke',
      })
    }
    map.clearMap()
    const all = []
    for (const day of props.plan.days || []) {
      const pts = []
      for (const s of day.spots || []) {
        const c = coords[s.name]
        if (!c) continue
        pts.push(c)
        all.push(c)
        new AMap.Marker({ position: c, title: s.name, map })
      }
      if (pts.length >= 2) drawRoute(AMap, pts)
    }
    if (all.length) map.setFitView()
    status.value = 'ok'
  } catch (e) {
    errorMsg.value = e?.message || String(e)
    status.value = 'error'
  }
}

onMounted(render)
watch(() => props.spotCoords, render, { deep: true })
onUnmounted(() => {
  if (map) {
    map.destroy()
    map = null
  }
})
</script>

<template>
  <div class="map-wrap">
    <div ref="mapEl" class="map"></div>
    <p v-if="status === 'nokey'" class="hint">未配置高德 JS Key（.env 的 AMAP_JS_KEY），地图不可用</p>
    <p v-else-if="status === 'error'" class="hint">地图加载失败：{{ errorMsg }}</p>
  </div>
</template>

<style scoped>
.map-wrap { margin-top: 14px; }
.map { width: 100%; height: 340px; border-radius: 10px; background: #f5f5f5; }
.hint { color: #999; font-size: 13px; }
</style>
