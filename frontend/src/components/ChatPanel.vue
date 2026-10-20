<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  messages: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  options: { type: Array, default: () => [] },
  tasks: { type: Array, default: null },
})
const emit = defineEmits(['send', 'resume'])
const input = ref('')
const checked = ref([])

watch(
  () => props.tasks,
  (tasks) => {
    checked.value = (tasks || []).map(() => true)
  },
  { immediate: true },
)

function argsText(args) {
  return JSON.stringify(args || {})
}

function confirmTasks() {
  const picked = (props.tasks || []).filter((_, i) => checked.value[i])
  if (!picked.length || props.loading) return
  emit('resume', picked)
}

function submit() {
  const text = input.value.trim()
  if (!text || props.loading || props.tasks) return
  emit('send', text)
  input.value = ''
}

function pick(o) {
  if (props.loading || props.tasks) return
  emit('send', o.value || o.label)
}
</script>

<template>
  <div class="chat">
    <div class="msgs">
      <div v-for="(m, i) in messages" :key="i" :class="['msg', m.role]">{{ m.text }}</div>
    </div>
    <div v-if="options.length" class="options">
      <button v-for="(o, i) in options" :key="i" class="opt" @click="pick(o)">
        <b>{{ o.label }}</b>
        <span v-if="o.desc">{{ o.desc }}</span>
      </button>
    </div>
    <div v-if="tasks && tasks.length" class="confirm">
      <div class="confirm-title">执行前确认任务清单（取消勾选可跳过）</div>
      <label v-for="(t, i) in tasks" :key="i" class="task">
        <input v-model="checked[i]" type="checkbox" />
        <b>{{ t.tool }}</b>
        <code>{{ argsText(t.args) }}</code>
      </label>
      <button class="confirm-btn" :disabled="loading || !checked.some(Boolean)" @click="confirmTasks">
        {{ loading ? '执行中…' : '确认并开始' }}
      </button>
    </div>
    <div class="input">
      <input
        v-model="input"
        :disabled="!!tasks"
        :placeholder="tasks ? '请先确认上方任务清单' : '描述你的出行需求，例如：上海两日游，预算1000，不爱走路'"
        @keyup.enter="submit"
      />
      <button :disabled="loading || !!tasks" @click="submit">{{ loading ? '规划中…' : '发送' }}</button>
    </div>
  </div>
</template>

<style scoped>
.chat { display: flex; flex-direction: column; height: 100%; }
.msgs { flex: 1; overflow-y: auto; padding: 10px; }
.msg { margin: 6px 0; padding: 8px 10px; border-radius: 8px; max-width: 82%; white-space: pre-wrap; }
.msg.user { background: #d6e4ff; margin-left: auto; }
.msg.bot { background: #f0f0f0; }
.msg.detail { background: #f7faf7; color: #3a7a52; font-size: 12.5px; border-left: 3px solid #5aa87a; }
.options { display: flex; flex-wrap: wrap; gap: 8px; padding: 6px 10px; }
.opt { display: flex; flex-direction: column; align-items: flex-start; text-align: left; gap: 2px;
  padding: 8px 12px; border: 1px solid #2c3e50; background: #fff; color: #2c3e50;
  border-radius: 10px; cursor: pointer; font-size: 13px; }
.opt:hover { background: #2c3e50; color: #fff; }
.opt span { font-size: 11px; opacity: 0.7; }
.confirm { margin: 6px 10px; padding: 10px; border: 1px solid #e0c36a; background: #fffbea; border-radius: 8px; }
.confirm-title { font-size: 13px; font-weight: 600; margin-bottom: 6px; }
.task { display: flex; align-items: center; gap: 6px; font-size: 12.5px; margin: 4px 0; }
.task code { color: #777; font-size: 11.5px; word-break: break-all; }
.confirm-btn { margin-top: 8px; padding: 6px 12px; border: none; background: #b7791f; color: #fff; border-radius: 6px; cursor: pointer; }
.confirm-btn:disabled { opacity: 0.55; cursor: default; }
.input { display: flex; gap: 8px; padding: 10px; border-top: 1px solid #eee; }
.input input { flex: 1; padding: 8px; border: 1px solid #ccc; border-radius: 6px; }
.input button { padding: 8px 14px; border: none; background: #2c3e50; color: #fff; border-radius: 6px; cursor: pointer; }
.input button:disabled { opacity: 0.6; cursor: default; }
</style>
