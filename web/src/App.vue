<script setup>
import { ref, computed, onMounted, watch, watchEffect } from 'vue'
import NewGamesPanel from './components/NewGamesPanel.vue'
import HotGamesPanel from './components/HotGamesPanel.vue'
import GameNewsPanel from './components/GameNewsPanel.vue'
import WeeklyDigestPanel from './components/WeeklyDigestPanel.vue'
import RefreshButton from './components/RefreshButton.vue'

// 各数据源分开加载与展示，一个失败不影响其它板块的可用性。
// key 与 data/*.json 的对应关系集中在这张表里，加减来源只改这里。
const FILES = {
  weekly: 'weekly_digest.json',
  taptap: 'taptap_upcoming.json',
  haoyou: 'haoyoukuaibao_upcoming.json',
  jiuyou: '9game_upcoming.json',
  p16: '16p_upcoming.json',
  hot: 'hot_games_dynamics.json',
  dmNews: '3dmgame_news.json',
  dmReviews: '3dmgame_reviews.json',
  dmDigest: '3dmgame_digest.json',
  yxNews: 'youxia_news.json',
  yxReviews: 'youxia_reviews.json',
  yxDigest: 'youxia_digest.json',
  gsNews: 'gamersky_news.json',
  gsReviews: 'gamersky_reviews.json',
  gsDigest: 'gamersky_digest.json',
  glNews: 'gamelook_news.json',
  glDigest: 'gamelook_digest.json',
  grNews: 'gameres_news.json',
  grDigest: 'gameres_digest.json',
}

const data = ref({})
const errors = ref({})
const loading = ref(true)

// 四个互斥板块（侧栏顺序即 SECTIONS 顺序），key 是 activeSection 的合法取值。
// 面板用 v-show 互斥显示以保留已加载 DOM；顶栏数据各源分开加载，一个失败不影响其它板块。
const SECTIONS = [
  ['weekly', '上周总览'],
  ['new-games', '新游监测'],
  ['hot-games', '热门动态'],
  ['news', '游戏资讯'],
]
const SECTION_KEYS = SECTIONS.map(([key]) => key)
const DEFAULT_SECTION = 'weekly'

// 顶层激活板块默认「上周总览」；上次选择的板块记在 localStorage，
// 刷新（F5）后停留在刷新前的板块。非法/缺失的历史值一律回退默认板块。
function initialSection() {
  const saved = localStorage.getItem('active-section')
  return SECTION_KEYS.includes(saved) ? saved : DEFAULT_SECTION
}
const activeSection = ref(initialSection())

// 点击切换板块时写入记忆，与主题的 localStorage 用法保持一致
watch(activeSection, (key) => localStorage.setItem('active-section', key))

const theme = ref(localStorage.getItem('theme') || '')

// data-theme 必须挂在 <html> 上：body 的背景色读的是 --bg，
// 挂在 App 根 div 上的话变量覆盖到不了 body 这个祖先节点，深色模式只会变一半。
watchEffect(() => {
  if (theme.value) document.documentElement.dataset.theme = theme.value
})

async function loadJson(name) {
  // 用 import.meta.env.BASE_URL 拼接数据路径，
  // 保证在 GitHub Pages 子路径（/competitor-dashboard/）部署下也能正确请求到 data/*.json
  const res = await fetch(`${import.meta.env.BASE_URL}data/${name}`)
  if (!res.ok) throw new Error(`请求 ${name} 失败：${res.status}`)
  return res.json()
}

onMounted(async () => {
  if (!theme.value) {
    theme.value = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  }

  const keys = Object.keys(FILES)
  const results = await Promise.allSettled(keys.map((k) => loadJson(FILES[k])))
  const nextData = {}
  const nextErrors = {}
  results.forEach((r, i) => {
    const key = keys[i]
    if (r.status === 'fulfilled') nextData[key] = r.value
    else nextErrors[key] = `数据加载失败：${r.reason?.message || '未知错误'}`
  })
  data.value = nextData
  errors.value = nextErrors
  loading.value = false
})

function toggleTheme() {
  theme.value = theme.value === 'dark' ? 'light' : 'dark'
  localStorage.setItem('theme', theme.value)
}

// RefreshButton 只在全部抓取成功时才 emit，因此这里拿到的一定是校验过的完整数据。
// 按 文件名 → key 反查后整体替换，并清掉对应的错误提示。
const KEY_BY_FILE = Object.fromEntries(Object.entries(FILES).map(([k, f]) => [f, k]))

function onRefreshed(payload) {
  const nextData = { ...data.value }
  const nextErrors = { ...errors.value }
  for (const [file, value] of Object.entries(payload)) {
    const key = KEY_BY_FILE[file]
    if (!key) continue
    nextData[key] = value
    delete nextErrors[key]
  }
  data.value = nextData
  errors.value = nextErrors
}

/* ---- 派生给各面板的数据 ---- */
const newGameErrors = computed(() => ({
  taptap: errors.value.taptap || '',
  haoyou: errors.value.haoyou || '',
  jiuyou: errors.value.jiuyou || '',
  p16: errors.value.p16 || '',
}))

// 每个资讯源的展示配置 + 数据在一处组装，面板只负责渲染
const newsSources = computed(() => [
  {
    key: 'dm',
    label: '3DMGame',
    reviewLabel: '测评',
    showReviews: true,
    news: data.value.dmNews,
    reviews: data.value.dmReviews,
    digest: data.value.dmDigest,
    newsError: errors.value.dmNews || '',
    reviewsError: errors.value.dmReviews || '',
    digestError: errors.value.dmDigest || '',
  },
  {
    key: 'yx',
    label: '游侠网',
    reviewLabel: '评测',
    showReviews: true,
    note: '游侠网游戏频道更新滞后约 1 天，当天内容由全站资讯补齐，因此可能夹带少量非游戏资讯——这是为避免漏掉当天新闻的有意取舍，不是采集错误，滞后内容会在次日采集时自动校正。',
    news: data.value.yxNews,
    reviews: data.value.yxReviews,
    digest: data.value.yxDigest,
    newsError: errors.value.yxNews || '',
    reviewsError: errors.value.yxReviews || '',
    digestError: errors.value.yxDigest || '',
  },
  {
    key: 'gs',
    label: '游民星空',
    reviewLabel: '评测',
    showReviews: true,
    note: '游民星空新闻合并「单机电玩 / NS / 手游 / 网游」四个频道；其中手游频道站点自 2026-07-31 起未再更新，10 天窗口内为 0 条，非抓取问题。',
    news: data.value.gsNews,
    reviews: data.value.gsReviews,
    digest: data.value.gsDigest,
    newsError: errors.value.gsNews || '',
    reviewsError: errors.value.gsReviews || '',
    digestError: errors.value.gsDigest || '',
  },
  {
    key: 'gl',
    label: 'GameLook',
    // GameLook 只有新闻没有评测
    showReviews: false,
    news: data.value.glNews,
    digest: data.value.glDigest,
    newsError: errors.value.glNews || '',
    digestError: errors.value.glDigest || '',
  },
  {
    key: 'gr',
    label: '游资网',
    // 游资网只有新闻没有评测
    showReviews: false,
    news: data.value.grNews,
    digest: data.value.grDigest,
    newsError: errors.value.grNews || '',
    digestError: errors.value.grDigest || '',
  },
])

// 侧栏条目计数：让人在切板块之前就知道各板块有多少内容
const counts = computed(() => ({
  weekly: (data.value.weekly?.hot_ranking || []).length,
  'new-games':
    (data.value.taptap || []).length +
    (data.value.haoyou?.days || []).reduce((n, d) => n + d.games.length, 0) +
    (data.value.jiuyou?.days || []).reduce((n, d) => n + d.games.length, 0) +
    (data.value.p16?.days || []).reduce((n, d) => n + d.games.length, 0),
  'hot-games': (data.value.hot?.publishers || []).reduce((n, p) => n + p.games.length, 0),
  news: newsSources.value.reduce((n, s) => n + (s.news?.items || []).length, 0),
}))

// 顶栏总时间戳取各源里最新的一个
const newestStamp = computed(() => {
  const list = [
    data.value.taptap?.[0]?.crawled_at,
    data.value.hot?.crawled_at,
    data.value.dmNews?.crawled_at,
    data.value.gsNews?.crawled_at,
  ].filter(Boolean)
  if (!list.length) return ''
  const iso = list.sort().pop()
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const p = (n) => String(n).padStart(2, '0')
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
})

const NEWS_FILES = [
  '3dmgame_news.json', '3dmgame_reviews.json', '3dmgame_digest.json',
  'youxia_news.json', 'youxia_reviews.json', 'youxia_digest.json',
  'gamersky_news.json', 'gamersky_reviews.json', 'gamersky_digest.json',
  'gamelook_news.json', 'gamelook_digest.json',
  'gameres_news.json', 'gameres_digest.json',
]
</script>

<template>
  <div class="app">

    <header class="app-bar">
      <h1>游戏行业监测看板</h1>
      <span class="spacer"></span>
      <span v-if="newestStamp" class="stamp">数据更新于 {{ newestStamp }}</span>
      <button class="icon-btn" title="切换深浅色" @click="toggleTheme">◐ 主题</button>
    </header>

    <div class="layout">
      <nav class="rail">
        <button
          v-for="[key, label] in SECTIONS"
          :key="key"
          class="rail-btn"
          :class="{ active: activeSection === key }"
          @click="activeSection = key"
        >
          <span>{{ label }}</span>
          <span class="count">{{ counts[key] || '' }}</span>
        </button>
      </nav>

      <main>
        <!-- 加载中用骨架屏占位，避免数据到位后整页跳动 -->
        <div v-if="loading" class="card">
          <div class="skel skel-line" style="width: 40%"></div>
          <div class="skel skel-line"></div>
          <div class="skel skel-line" style="width: 80%"></div>
        </div>

        <template v-else>
          <section v-show="activeSection === 'weekly'" class="card">
            <div class="card-head">
              <h2>上周总览</h2>
              <span class="spacer"></span>
              <RefreshButton
                :files="['weekly_digest.json']"
                storage-key="weekly-digest"
                @refreshed="onRefreshed"
              />
            </div>
            <WeeklyDigestPanel :data="data.weekly" :error="errors.weekly || ''" />
          </section>

          <section v-show="activeSection === 'new-games'" class="card">
            <div class="card-head">
              <h2>新游监测</h2>
              <span class="spacer"></span>
              <RefreshButton
                :files="['taptap_upcoming.json', 'haoyoukuaibao_upcoming.json', '9game_upcoming.json', '16p_upcoming.json']"
                storage-key="new-games"
                @refreshed="onRefreshed"
              />
            </div>
            <NewGamesPanel
              :taptap="data.taptap || []"
              :haoyou="data.haoyou"
              :jiuyou="data.jiuyou"
              :p16="data.p16"
              :errors="newGameErrors"
              :active="activeSection === 'new-games'"
            />
          </section>

          <section v-show="activeSection === 'hot-games'" class="card">
            <div class="card-head">
              <h2>热门游戏动态监测</h2>
              <span class="spacer"></span>
              <RefreshButton
                :files="['hot_games_dynamics.json']"
                storage-key="hot-games"
                @refreshed="onRefreshed"
              />
            </div>
            <HotGamesPanel
              :data="data.hot"
              :error="errors.hot || ''"
              :active="activeSection === 'hot-games'"
            />
          </section>

          <section v-show="activeSection === 'news'" class="card">
            <div class="card-head">
              <h2>游戏资讯</h2>
              <span class="spacer"></span>
              <RefreshButton :files="NEWS_FILES" storage-key="game-news" @refreshed="onRefreshed" />
            </div>
            <GameNewsPanel :sources="newsSources" :active="activeSection === 'news'" />
          </section>
        </template>
      </main>
    </div>
  </div>
</template>

<style scoped>
.app-bar {
  position: sticky;
  top: 0;
  z-index: 20;
  display: flex;
  align-items: center;
  gap: 12px;
  height: var(--app-bar-h);
  padding: 0 20px;
  background: var(--surface-glass);
  -webkit-backdrop-filter: var(--glass-blur);
  backdrop-filter: var(--glass-blur);
  border-bottom: 1px solid var(--border);
}

/* 与 style.css 里 .tab-stack 同样的兜底：拿不到模糊就退回不透明底色 */
@supports not ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
  .app-bar {
    background: var(--surface);
  }
}

.app-bar h1 {
  margin: 0;
  font-size: 16px;
  font-weight: 650;
  letter-spacing: .2px;
}

.app-bar .spacer { flex: 1; }

.layout {
  display: grid;
  grid-template-columns: 200px minmax(0, 1fr);
  gap: 24px;
  max-width: 1400px;
  margin: 0 auto;
  padding: 24px 20px 64px;
}

.rail {
  position: sticky;
  top: calc(var(--app-bar-h) + 24px);
  align-self: start;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.rail-btn {
  border: none;
  background: none;
  text-align: left;
  padding: 9px 12px;
  border-radius: var(--r-sm);
  font-size: 14px;
  font-family: var(--font);
  color: var(--text-2);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.rail-btn:hover { background: var(--surface-2); color: var(--text); }
.rail-btn.active { background: var(--brand-weak); color: var(--brand); font-weight: 600; }

.rail-btn .count {
  font-size: 11px;
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
}

.rail-btn.active .count { color: var(--brand); }

@media (max-width: 960px) {
  .layout {
    grid-template-columns: minmax(0, 1fr);
    gap: 12px;
    padding: 16px 12px 48px;
  }

  .rail {
    position: static;
    flex-direction: row;
    overflow-x: auto;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 999px;
    padding: 3px;
  }

  .rail-btn { border-radius: 999px; white-space: nowrap; }
}
</style>
