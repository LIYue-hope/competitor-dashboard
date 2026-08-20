// 竞品看板「数据更新」按钮的 Serverless 代理（Cloudflare Worker）。
//
// 为什么需要它：
//   看板是纯静态站（GitHub Pages），前端没有后端可以跑 Python 采集脚本。要让
//   按钮真正触发重新抓取，只能调 GitHub 的 workflow_dispatch API，而这个 API
//   必须带 token。站点是公开的，token 一旦进前端产物就等于公开泄露（任何人都
//   能拿它写仓库），所以必须由这一层代理持有 token，前端只跟代理说话。
//
// 对外只有两个接口：
//   POST /api/refresh   body: { section }        -> { run_id }
//   GET  /api/status?run_id=123                 -> { status, conclusion }
//
// 需要配置的环境变量（wrangler secret / Dashboard 里配，不要写进代码）：
//   GITHUB_TOKEN    仓库 fine-grained PAT，权限只需 Actions: read and write
//   REFRESH_KEY     前端访问口令。站点公开，没有它等于把 CI 额度开给公网
//   REPO            owner/repo，例如 LIYue-hope/competitor-dashboard
//   ALLOWED_ORIGIN  允许的前端来源，例如 https://liyue-hope.github.io
// 可选绑定：
//   STATE           KV namespace，用于服务端冷却。不绑定则只有前端 localStorage
//                   冷却，而那个冷却清一下浏览器数据就没了，拦不住恶意请求。

const WORKFLOW_FILE = 'crawl.yml'
const BRANCH = 'main'

// 与前端按钮的板块划分一一对应，crawl.yml 的 inputs.section 只接受这几个值
const ALLOWED_SECTIONS = new Set(['new-games', 'hot-games', 'news'])

// 服务端冷却：与前端 2 小时保持一致。前端冷却是体验层（避免误触），
// 这里才是真正的保护层
const COOLDOWN_SECONDS = 2 * 60 * 60

const GITHUB_API = 'https://api.github.com'

function corsHeaders(env) {
  return {
    'Access-Control-Allow-Origin': env.ALLOWED_ORIGIN || '*',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, X-Refresh-Key',
    'Access-Control-Max-Age': '86400',
  }
}

function json(body, status, env) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...corsHeaders(env) },
  })
}

// 定长比较，避免用 === 比较口令时通过响应耗时逐字符猜解
function timingSafeEqual(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string' || a.length !== b.length) return false
  let diff = 0
  for (let i = 0; i < a.length; i += 1) {
    diff |= a.charCodeAt(i) ^ b.charCodeAt(i)
  }
  return diff === 0
}

function githubHeaders(env) {
  return {
    Authorization: `Bearer ${env.GITHUB_TOKEN}`,
    Accept: 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
    // GitHub API 强制要求 User-Agent，缺了直接 403
    'User-Agent': 'competitor-dashboard-refresh-worker',
  }
}

// dispatch 接口返回 204 且不带 run id，只能反查最近的 workflow_dispatch run。
// 用「创建时间不早于点击时刻」过滤，取最新的一条。
// 已知局限：若两个板块在同一秒各自触发，可能拿到对方的 run id。这只会让状态
// 显示略有偏差（两个 run 时长接近），不会造成重复触发或数据错乱。
async function findRunId(env, sinceMs) {
  const since = new Date(sinceMs - 60_000).toISOString()
  const url =
    `${GITHUB_API}/repos/${env.REPO}/actions/workflows/${WORKFLOW_FILE}/runs` +
    `?event=workflow_dispatch&per_page=10&created=%3E%3D${encodeURIComponent(since)}`

  for (let attempt = 0; attempt < 6; attempt += 1) {
    const res = await fetch(url, { headers: githubHeaders(env) })
    if (res.ok) {
      const data = await res.json()
      const runs = (data.workflow_runs || []).filter(
        (run) => Date.parse(run.created_at) >= sinceMs - 60_000,
      )
      if (runs.length > 0) {
        runs.sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))
        return runs[0].id
      }
    }
    // run 记录不是 dispatch 返回 204 的瞬间就可见，需要短暂等待后重试
    await new Promise((resolve) => setTimeout(resolve, 1500))
  }
  return null
}

async function handleRefresh(request, env) {
  let body
  try {
    body = await request.json()
  } catch {
    return json({ error: 'invalid json' }, 400, env)
  }

  const section = body && body.section
  if (!ALLOWED_SECTIONS.has(section)) {
    return json({ error: 'unknown section' }, 400, env)
  }

  const cooldownKey = `cooldown:${section}`
  if (env.STATE) {
    const until = await env.STATE.get(cooldownKey)
    if (until && Number(until) > Date.now()) {
      return json(
        { error: 'cooling', retry_after: Math.ceil((Number(until) - Date.now()) / 1000) },
        429,
        env,
      )
    }
  }

  const startedAt = Date.now()
  const dispatch = await fetch(
    `${GITHUB_API}/repos/${env.REPO}/actions/workflows/${WORKFLOW_FILE}/dispatches`,
    {
      method: 'POST',
      headers: { ...githubHeaders(env), 'Content-Type': 'application/json' },
      body: JSON.stringify({ ref: BRANCH, inputs: { section } }),
    },
  )

  if (dispatch.status !== 204) {
    const detail = await dispatch.text()
    // 不把 GitHub 的原始响应透给前端，避免泄露仓库/权限细节
    console.error('dispatch failed', dispatch.status, detail)
    return json({ error: 'dispatch failed' }, 502, env)
  }

  // 冷却在触发成功后立刻写入：即使后面反查 run id 失败，采集也已经在跑，
  // 不能让调用方靠重试绕过冷却。TTL 由 KV 负责过期，无需清理。
  if (env.STATE) {
    await env.STATE.put(cooldownKey, String(Date.now() + COOLDOWN_SECONDS * 1000), {
      expirationTtl: COOLDOWN_SECONDS,
    })
  }

  const runId = await findRunId(env, startedAt)
  return json({ run_id: runId }, 202, env)
}

async function handleStatus(url, env) {
  const runId = url.searchParams.get('run_id')
  // 只接受纯数字，防止把任意路径拼进 GitHub API URL
  if (!runId || !/^\d+$/.test(runId)) {
    return json({ error: 'invalid run_id' }, 400, env)
  }

  const res = await fetch(`${GITHUB_API}/repos/${env.REPO}/actions/runs/${runId}`, {
    headers: githubHeaders(env),
  })
  if (!res.ok) {
    return json({ error: 'run not found' }, 404, env)
  }

  const run = await res.json()
  // status: queued | in_progress | completed
  // conclusion: success | failure | cancelled | ...（未完成时为 null）
  return json({ status: run.status, conclusion: run.conclusion }, 200, env)
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url)

    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: corsHeaders(env) })
    }

    if (!env.GITHUB_TOKEN || !env.REFRESH_KEY || !env.REPO) {
      return json({ error: 'worker not configured' }, 500, env)
    }

    // 两个接口都要带口令：status 也会消耗 GitHub API 配额，不能裸奔
    if (!timingSafeEqual(request.headers.get('X-Refresh-Key') || '', env.REFRESH_KEY)) {
      return json({ error: 'unauthorized' }, 401, env)
    }

    if (request.method === 'POST' && url.pathname === '/api/refresh') {
      return handleRefresh(request, env)
    }
    if (request.method === 'GET' && url.pathname === '/api/status') {
      return handleStatus(url, env)
    }

    return json({ error: 'not found' }, 404, env)
  },
}
