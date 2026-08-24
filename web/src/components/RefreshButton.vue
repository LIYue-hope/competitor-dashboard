<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'

// 板块级"数据更新"按钮。
//
// 数据来源说明：
//   本站是纯静态站（GitHub Pages），前端无法触发 Python 采集脚本重新抓取。
//   因此这里的"更新"指的是直接从仓库 main 分支拉取最新的 data/*.json——
//   crawl job 推送数据后 raw 立即可见，不必等 Pages 重新构建部署，
//   所以它拿到的数据可能比当前页面（构建产物）更新。
//   需要真正重新抓取时，去 Actions 手动触发 workflow，再点本按钮取结果。
const RAW_BASE = 'https://raw.githubusercontent.com/LIYue-hope/competitor-dashboard/main/data'

const SUCCESS_COOLDOWN_MS = 2 * 60 * 60 * 1000 // 刷新成功后 2 小时内不可再刷，避免短时间重复请求
const FAIL_COOLDOWN_MS = 30 * 60 * 1000 // 刷新失败后 30 分钟即可重试
const MAX_ATTEMPTS = 3
const RETRY_WAIT_MS = 1000

const props = defineProps({
  // 本板块涉及的数据文件名，全部成功才算刷新成功
  files: {
    type: Array,
    required: true,
  },
  // localStorage 中记录冷却状态的键后缀，各板块独立
  storageKey: {
    type: String,
    required: true,
  },
})

// 刷新成功后把 { 文件名: 解析后的数据 } 交给父组件写入页面
const emit = defineEmits(['refreshed'])

// idle：可点击；loading：刷新中；done：刷新完成；failed：刷新失败
const state = ref('idle')
const cooldownUntil = ref(0)
const now = ref(Date.now())
let timer = null

const cooling = computed(() => cooldownUntil.value > now.value)
const disabled = computed(() => state.value === 'loading' || cooling.value)

const label = computed(() => {
  if (state.value === 'loading') return ''
  if (state.value === 'done') return '刷新完成'
  if (state.value === 'failed') return '刷新失败'
  return '数据更新'
})

// 剩余冷却时间格式化为 时:分:秒（不足 1 小时省略小时段）
const countdown = computed(() => {
  const remain = Math.max(0, cooldownUntil.value - now.value)
  const total = Math.ceil(remain / 1000)
  const pad = (n) => String(n).padStart(2, '0')
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`
})

const stateKey = computed(() => `refresh:${props.storageKey}`)

function persist() {
  localStorage.setItem(
    stateKey.value,
    JSON.stringify({ until: cooldownUntil.value, result: state.value }),
  )
}

function restore() {
  try {
    const raw = localStorage.getItem(stateKey.value)
    if (!raw) return
    const saved = JSON.parse(raw)
    if (saved && saved.until > Date.now()) {
      cooldownUntil.value = saved.until
      state.value = saved.result === 'failed' ? 'failed' : 'done'
    }
  } catch {
    // 本地记录损坏时忽略，按可刷新处理
  }
}

// 数据合法性校验：空数组 / 空对象都视为抓取异常，不能用来覆盖页面上的既有数据
function isValid(payload) {
  if (payload === null || typeof payload !== 'object') return false
  if (Array.isArray(payload)) return payload.length > 0
  return Object.keys(payload).length > 0
}

async function fetchOnce() {
  const stamp = Date.now()
  const results = await Promise.all(
    props.files.map(async (name) => {
      const res = await fetch(`${RAW_BASE}/${name}?t=${stamp}`, { cache: 'no-store' })
      if (!res.ok) throw new Error(`${name} ${res.status}`)
      const data = await res.json()
      if (!isValid(data)) throw new Error(`${name} 数据为空`)
      return [name, data]
    }),
  )
  return Object.fromEntries(results)
}

async function handleClick() {
  if (disabled.value) return

  state.value = 'loading'

  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt += 1) {
    try {
      const payload = await fetchOnce()
      emit('refreshed', payload)
      state.value = 'done'
      cooldownUntil.value = Date.now() + SUCCESS_COOLDOWN_MS
      persist()
      return
    } catch {
      if (attempt < MAX_ATTEMPTS) {
        await new Promise((resolve) => setTimeout(resolve, RETRY_WAIT_MS))
      }
    }
  }

  // 三次都失败：不 emit，页面保留原有数据，冷却缩短为半小时
  state.value = 'failed'
  cooldownUntil.value = Date.now() + FAIL_COOLDOWN_MS
  persist()
}

onMounted(() => {
  restore()
  timer = setInterval(() => {
    now.value = Date.now()
  }, 1000)
})

onUnmounted(() => {
  clearInterval(timer)
})
</script>

<template>
  <span class="refresh-wrap">
    <button
      class="icon-btn refresh-btn"
      :class="[state, { cooling }]"
      :disabled="disabled"
      :title="state === 'failed' ? '抓取失败，已保留原有数据' : '从仓库拉取最新采集数据'"
      @click="handleClick"
    >
      <span v-if="state === 'loading'" class="spin" aria-label="刷新中">⟳</span>
      <template v-else>{{ label }}</template>
    </button>
    <span v-if="cooling" class="countdown">下次可刷新 {{ countdown }}</span>
  </span>
</template>

<style scoped>
.refresh-wrap {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-weight: 400;
}

/* 视觉走 style.css 的 .icon-btn，这里只补按钮宽度和成功 / 失败两种语义色 */
.refresh-btn {
  min-width: 76px;
  justify-content: center;
  height: 28px;
  font-size: 12px;
}

.refresh-btn.done { color: var(--ok); border-color: var(--ok); }
.refresh-btn.failed { color: var(--danger); border-color: var(--danger); }

.spin {
  display: inline-block;
  animation: refresh-spin 0.9s linear infinite;
}

@keyframes refresh-spin {
  to {
    transform: rotate(360deg);
  }
}

.countdown {
  font-size: 12px;
  color: var(--text-3);
}
</style>

