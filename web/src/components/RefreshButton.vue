<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'

// 板块级「数据更新」按钮：点一下真正重新抓一遍该板块的数据。
//
// 完整链路：
//   1. POST {API}/api/refresh { section }  -> Serverless 代理用它保管的 token 调
//      GitHub workflow_dispatch，只跑该板块对应的采集脚本，返回 run_id
//   2. 轮询 GET {API}/api/status?run_id=  -> 等到 status === 'completed'
//   3. 从 raw.githubusercontent 拉这一板块的 data/*.json（采集 job 已 push，
//      raw 立刻可见，不必等 Pages 重新构建部署）
//   4. 校验非空后整体替换页面数据
//
// 为什么要经过代理：站点是公开静态站，token 放前端等于公开写权限。代理见
// worker/src/index.js。未配置 VITE_REFRESH_API 时自动退化为"只拉 raw 最新数据、
// 不触发采集"，本地开发和没部署代理的情况下按钮依然可用。
const RAW_BASE = 'https://raw.githubusercontent.com/LIYue-hope/competitor-dashboard/main/data'

// 构建期注入。web/.env.local 或 CI 的 VITE_REFRESH_API 里配代理地址（不带尾斜杠）
const API_BASE = (import.meta.env.VITE_REFRESH_API || '').replace(/\/$/, '')

const SUCCESS_COOLDOWN_MS = 2 * 60 * 60 * 1000 // 刷新成功后 2 小时内不可再刷，避免短时间重复触发采集
const FAIL_COOLDOWN_MS = 30 * 60 * 1000 // 刷新失败后 30 分钟即可重试
const FETCH_ATTEMPTS = 3 // 只重试"拉数据"，绝不重试"触发采集"，否则一次点击会起多个 run
const FETCH_RETRY_WAIT_MS = 1000
const POLL_INTERVAL_MS = 10 * 1000
const RUN_TIMEOUT_MS = 8 * 60 * 1000 // 单板块采集通常 1~2 分钟，留足排队余量

const props = defineProps({
  // 对应 crawl.yml 的 inputs.section，同时用作 localStorage 键后缀
  section: {
    type: String,
    required: true,
  },
  // 本板块涉及的数据文件名，全部拉取成功且非空才算刷新成功
  files: {
    type: Array,
    required: true,
  },
})

// 刷新成功后把 { 文件名: 解析后的数据 } 交给父组件写入页面
const emit = defineEmits(['refreshed'])

// idle：可点击；dispatching：正在触发采集；running：采集进行中；
// fetching：采集完成、正在拉数据；done：刷新完成；failed：刷新失败
const state = ref('idle')
const cooldownUntil = ref(0)
const now = ref(Date.now())
let ticker = null

const busy = computed(() => ['dispatching', 'running', 'fetching'].includes(state.value))
const cooling = computed(() => cooldownUntil.value > now.value)
const disabled = computed(() => busy.value || cooling.value)

const label = computed(() => {
  if (busy.value) return ''
  if (state.value === 'done') return '刷新完成'
  if (state.value === 'failed') return '刷新失败'
  return '数据更新'
})

// 采集要跑一两分钟，光转圈用户不知道卡在哪一步，给一句状态说明
const hint = computed(() => {
  if (state.value === 'dispatching') return '正在触发采集'
  if (state.value === 'running') return '采集中，请稍候'
  if (state.value === 'fetching') return '正在拉取新数据'
  return ''
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

const stateKey = computed(() => `refresh:${props.section}`)
const KEY_STORAGE = 'refresh:access-key'

function persist(extra = {}) {
  localStorage.setItem(
    stateKey.value,
    JSON.stringify({ until: cooldownUntil.value, result: state.value, ...extra }),
  )
}

function readSaved() {
  try {
    return JSON.parse(localStorage.getItem(stateKey.value) || 'null')
  } catch {
    // 本地记录损坏时忽略，按可刷新处理
    return null
  }
}

// 访问口令：站点公开，代理必须校验口令，否则等于把 CI 额度开放给公网。
// 首次点击时询问一次并存在本地，之后无感。
function accessKey() {
  let key = localStorage.getItem(KEY_STORAGE)
  if (!key) {
    key = window.prompt('请输入数据更新口令（只需输入一次，保存在本地浏览器）') || ''
    if (key) localStorage.setItem(KEY_STORAGE, key)
  }
  return key
}

async function api(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { ...(options.headers || {}), 'X-Refresh-Key': accessKey() },
  })
  if (res.status === 401) {
    // 口令错了就清掉，下次点击重新询问，而不是一直静默失败
    localStorage.removeItem(KEY_STORAGE)
    throw new Error('unauthorized')
  }
  return res
}

// 数据合法性校验：空数组 / 空对象都视为抓取异常，不能用来覆盖页面上的既有数据
function isValid(payload) {
  if (payload === null || typeof payload !== 'object') return false
  if (Array.isArray(payload)) return payload.length > 0
  return Object.keys(payload).length > 0
}

async function fetchRawOnce() {
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

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

function succeed(payload) {
  emit('refreshed', payload)
  state.value = 'done'
  cooldownUntil.value = Date.now() + SUCCESS_COOLDOWN_MS
  persist()
}

// 不 emit，页面保留原有数据；冷却缩短为半小时，便于尽快重试
function fail() {
  state.value = 'failed'
  cooldownUntil.value = Date.now() + FAIL_COOLDOWN_MS
  persist()
}

// 采集完成后拉数据。这一层可以安全重试：raw 是只读请求，重试不会再起采集。
async function fetchWithRetry() {
  state.value = 'fetching'
  for (let attempt = 1; attempt <= FETCH_ATTEMPTS; attempt += 1) {
    try {
      return await fetchRawOnce()
    } catch {
      if (attempt < FETCH_ATTEMPTS) await sleep(FETCH_RETRY_WAIT_MS)
    }
  }
  return null
}

// 轮询 run 状态直到结束。deadline 用绝对时间戳，刷新页面续跑时也能正确判超时。
// 采集 workflow 里失败的源被 continue-on-error 吞掉后又用 exit 1 重新暴露，
// 所以 conclusion 为 failure 只说明"至少一个源挂了"，成功的源数据仍然已经 push。
// 因此这里不因 failure 直接判负，仍去拉数据，由非空校验决定成败。
async function waitForRun(runId, deadline) {
  state.value = 'running'
  while (Date.now() < deadline) {
    await sleep(POLL_INTERVAL_MS)
    try {
      const res = await api(`/api/status?run_id=${runId}`)
      if (res.ok) {
        const { status } = await res.json()
        if (status === 'completed') return true
      }
    } catch {
      // 单次轮询失败（网络抖动 / 口令失效）不立即判负，继续等到超时
    }
  }
  return false
}

async function handleClick() {
  if (disabled.value) return

  // 没配代理：退化成只拉 raw 上已有的最新数据，不触发采集
  if (!API_BASE) {
    state.value = 'fetching'
    const payload = await fetchWithRetry()
    if (payload) succeed(payload)
    else fail()
    return
  }

  state.value = 'dispatching'
  let runId = null
  try {
    const res = await api('/api/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ section: props.section }),
    })

    if (res.status === 429) {
      // 服务端冷却未到（本地记录被清过）。按服务端给的剩余时间对齐，不算失败。
      const { retry_after: retryAfter } = await res.json().catch(() => ({}))
      state.value = 'idle'
      cooldownUntil.value = Date.now() + (Number(retryAfter) || 1800) * 1000
      persist()
      return
    }
    if (!res.ok) throw new Error(`dispatch ${res.status}`)

    runId = (await res.json()).run_id
  } catch {
    fail()
    return
  }

  const deadline = Date.now() + RUN_TIMEOUT_MS

  // run_id 反查失败（代理没能及时看到 run 记录）：采集其实已经触发，
  // 不能重发，退化为固定等待一段时间后直接拉数据。
  if (!runId) {
    state.value = 'running'
    await sleep(90 * 1000)
  } else {
    // 记下 run_id，刷新/关掉页面后回来能接着轮询，而不是重新触发一次采集
    persist({ runId, deadline })
    const finished = await waitForRun(runId, deadline)
    if (!finished) {
      fail()
      return
    }
  }

  const payload = await fetchWithRetry()
  if (payload) succeed(payload)
  else fail()
}

// 上次离开页面时采集还没跑完：接着轮询，避免重复触发
async function resume(saved) {
  const finished = await waitForRun(saved.runId, saved.deadline)
  if (!finished) {
    fail()
    return
  }
  const payload = await fetchWithRetry()
  if (payload) succeed(payload)
  else fail()
}

onMounted(() => {
  const saved = readSaved()
  if (saved) {
    if (saved.runId && saved.deadline > Date.now() && !['done', 'failed'].includes(saved.result)) {
      resume(saved)
    } else if (saved.until > Date.now()) {
      cooldownUntil.value = saved.until
      state.value = saved.result === 'failed' ? 'failed' : 'done'
    }
  }
  ticker = setInterval(() => {
    now.value = Date.now()
  }, 1000)
})

onUnmounted(() => {
  clearInterval(ticker)
})
</script>

<template>
  <span class="refresh-wrap">
    <button
      class="refresh-btn"
      :class="[state, { cooling }]"
      :disabled="disabled"
      :title="state === 'failed' ? '抓取失败，已保留原有数据' : '重新采集本板块数据'"
      @click="handleClick"
    >
      <span v-if="busy" class="spin" aria-label="刷新中">⟳</span>
      <template v-else>{{ label }}</template>
    </button>
    <span v-if="hint" class="hint">{{ hint }}</span>
    <span v-else-if="cooling" class="countdown">下次可刷新 {{ countdown }}</span>
  </span>
</template>

<style scoped>
.refresh-wrap {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-left: 12px;
  font-weight: 400;
}

.refresh-btn {
  min-width: 72px;
  padding: 4px 12px;
  font-size: 12px;
  line-height: 18px;
  color: #1976d2;
  background: #fff;
  border: 1px solid #90caf9;
  border-radius: 4px;
  cursor: pointer;
}

.refresh-btn:hover:not(:disabled) {
  background: #e3f2fd;
}

.refresh-btn:disabled {
  cursor: default;
}

.refresh-btn.done {
  color: #2e7d32;
  border-color: #a5d6a7;
}

.refresh-btn.failed {
  color: #d32f2f;
  border-color: #ef9a9a;
}

.spin {
  display: inline-block;
  animation: refresh-spin 0.9s linear infinite;
}

@keyframes refresh-spin {
  to {
    transform: rotate(360deg);
  }
}

.countdown,
.hint {
  font-size: 12px;
  color: #888;
}
</style>
