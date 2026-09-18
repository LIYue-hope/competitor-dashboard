<script setup>
import { ref, computed, onMounted, onUnmounted, watch, watchEffect, nextTick } from 'vue'
import NewGamesPanel from './components/NewGamesPanel.vue'
import HotGamesPanel from './components/HotGamesPanel.vue'
import GameNewsPanel from './components/GameNewsPanel.vue'
import DailyNewsTrend from './components/DailyNewsTrend.vue'
import WeeklyDigestPanel from './components/WeeklyDigestPanel.vue'
import HistoryDataPanel from './components/HistoryDataPanel.vue'
import RefreshButton from './components/RefreshButton.vue'

// 各数据源分开加载与展示，一个失败不影响其它板块的可用性。
// key 与 data/*.json 的对应关系集中在这张表里，加减来源只改这里。
const FILES = {
  weekly: 'weekly_digest.json',
  weeklyHistory: 'weekly_history.json',
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
  dailyNewsHistory: 'daily_news_history.json',
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
  ['history', '历史数据'],
]
const SECTION_KEYS = SECTIONS.map(([key]) => key)
const DEFAULT_SECTION = 'weekly'

// 顶层激活板块默认「上周总览」；上次选择的板块记在 localStorage，
// 刷新（F5）后停留在刷新前的板块。非法/缺失的历史值一律回退默认板块。
function initialSection() {
  const shared = new URLSearchParams(window.location.search).get('section')
  if (SECTION_KEYS.includes(shared)) return shared
  const saved = localStorage.getItem('active-section')
  return SECTION_KEYS.includes(saved) ? saved : DEFAULT_SECTION
}
const activeSection = ref(initialSection())
const expandedSection = ref('')
const activeSubAnchor = ref('')

// 侧栏既可作为一级页面入口，也可展开当前板块中的可跳转小标题。
// 子项 anchor 都是稳定的 DOM id，数据刷新时仍可准确定位。
const SECTION_NAV = {
  weekly: [['weekly-overview', '上周综述'], ['weekly-hot-ranking', '综合热度榜']],
  'new-games': [['new-games-content', '各网站新游']],
  'hot-games': [['hot-games-content', '游戏动态']],
  news: [['news-content', '资讯列表'], ['news-daily-trend', '每日新增曲线']],
  history: [['history-heat-ranking', '历史热度榜'], ['history-news-ranking', '历史游戏资讯榜']],
}

function selectSection(key) {
  activeSection.value = key
  // 切换一级 Tab 只替换右侧内容，保留当前滚动位置，顶部的数据概览不会被自动带走。
  expandedSection.value = key
  activeSubAnchor.value = ''
  nextTick(updateActiveSubAnchor)
}
function toggleSection(key) {
  expandedSection.value = expandedSection.value === key ? '' : key
}
function jumpToSection(key, anchor) {
  activeSection.value = key
  expandedSection.value = key
  activeSubAnchor.value = anchor
  nextTick(() => document.getElementById(anchor)?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
}

// 滚动到某个内容锚点时同步高亮侧栏小标题；阈值避开顶栏和资讯面板吸顶栏。
function updateActiveSubAnchor() {
  const anchors = SECTION_NAV[activeSection.value] || []
  const threshold = 90
  let current = ''
  for (const [anchor] of anchors) {
    const element = document.getElementById(anchor)
    if (element && element.getBoundingClientRect().top <= threshold) current = anchor
  }
  activeSubAnchor.value = current
}

// 点击切换板块时写入记忆，与主题的 localStorage 用法保持一致
watch(activeSection, (key) => {
  localStorage.setItem('active-section', key)
  const url = new URL(window.location.href)
  url.searchParams.set('section', key)
  window.history.replaceState({}, '', url)
})
watch(activeSection, () => nextTick(() => {
  // 点击子标题跨板块跳转时先保留用户刚选中的高亮，滚动事件会在抵达后继续校正。
  if (!activeSubAnchor.value) updateActiveSubAnchor()
}))

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
  nextTick(updateActiveSubAnchor)
})

onMounted(() => {
  window.addEventListener('scroll', updateActiveSubAnchor, { passive: true })
  nextTick(updateActiveSubAnchor)
})

onUnmounted(() => window.removeEventListener('scroll', updateActiveSubAnchor))

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

// 新快照尚未部署、或某次请求失败时，仍用已加载的五份滚动资讯数据画出可用曲线。
// 快照一旦可用就始终优先使用，fallback 仅覆盖当前新闻窗口，明确标为临时数据。
const dailyNewsTrendData = computed(() => {
  const snapshot = data.value.dailyNewsHistory
  const DAILY_NEWS_START_DATE = '2026-09-01'
  const sourceMeta = snapshot?.sources?.length
    ? snapshot.sources
    : newsSources.value.map(({ key, label }) => ({ key, label }))
  const rows = new Map((snapshot?.days || []).map((day) => [
    day.date,
    { date: day.date, counts: { ...(day.counts || {}) } },
  ]))
  const todayParts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(new Date())
  const today = `${todayParts.find((part) => part.type === 'year').value}-${todayParts.find((part) => part.type === 'month').value}-${todayParts.find((part) => part.type === 'day').value}`
  for (const source of newsSources.value) {
    // 只有成功加载且结构有效的来源才覆盖快照，避免一次刷新失败把历史值改成 0。
    if (!Array.isArray(source.news?.items)) continue
    const counts = {}
    for (const item of source.news.items) {
      const date = String(item.published_at || '').slice(0, 10)
      if (!date || date < DAILY_NEWS_START_DATE) continue
      counts[date] = (counts[date] || 0) + 1
    }
    // 成功读取但当天没有文章时也要明确记录 0；读取失败的来源在上面的 guard 已跳过。
    if (today >= DAILY_NEWS_START_DATE && counts[today] === undefined) counts[today] = 0
    for (const [date, count] of Object.entries(counts)) {
      if (!rows.has(date)) rows.set(date, { date, counts: {} })
      rows.get(date).counts[source.key] = count
    }
  }
  if (!rows.size) return null
  return {
    ...(snapshot || {}),
    start_date: snapshot?.start_date || [...rows.keys()].sort()[0],
    temporary: !snapshot?.days?.length,
    sources: sourceMeta,
    // 刷新资讯后用刚加载的新闻覆盖相同日期，曲线无需等待下一次页面加载。
    days: [...rows.values()].sort((a, b) => a.date.localeCompare(b.date)).map((day) => ({
      date: day.date,
      // 缺失键表示该来源当日不可用，不能在展示层再伪造成 0 条。
      counts: Object.fromEntries(sourceMeta.flatMap((source) => {
        const value = day.counts?.[source.key]
        return Number.isFinite(value) ? [[source.key, value]] : []
      })),
    })),
  }
})
const dailyNewsTrendError = computed(() => dailyNewsTrendData.value ? '' : (errors.value.dailyNewsHistory || ''))

// 概览里的「挂机/搬砖新游」按游戏名和实际上架日归并：同一游戏当天在多个站点出现时，
// 只显示一行平台列表；若各站点的上架日不同，则保留为同一游戏下的多行时间。
// 好游快爆的日期格偶尔是预下载日，优先从活动文案中提取明确的「x 月 x 日上线」日期。
function displayGameName(name = '') {
  return String(name).trim().replace(/[-—]\s*(?:预下载|(?:(?:\d{1,2}月\d{1,2}日)?(?:正式)?上线))\s*$/, '')
}
function gameKey(name = '') {
  return displayGameName(name)
    .toLocaleLowerCase()
    .replace(/[\s!！:：,，.。'"“”‘’()（）\-—_]/g, '')
}
function haoyouReleaseDate(dayDate, eventDesc = '') {
  const match = String(eventDesc).match(/(\d{1,2})月(\d{1,2})日[^。；，,]*(?:正式)?上线/)
  if (!match || !/^\d{4}-\d{2}-\d{2}$/.test(dayDate || '')) return dayDate
  return `${dayDate.slice(0, 4)}-${match[1].padStart(2, '0')}-${match[2].padStart(2, '0')}`
}
function shortDate(date = '') {
  const match = String(date).match(/^\d{4}-(\d{2})-(\d{2})$/)
  return match ? `${match[1]}月${match[2]}日` : date
}

const afkUpcomingGames = computed(() => {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date())
  const today = `${parts.find((part) => part.type === 'year').value}-${parts.find((part) => part.type === 'month').value}-${parts.find((part) => part.type === 'day').value}`
  const dateBefore = (date, offset) => new Date(Date.parse(`${date}T00:00:00Z`) + offset * 86400000).toISOString().slice(0, 10)
  const end = dateBefore(today, 7)
  const entries = [
    ...(data.value.taptap || []).map((game) => ({ ...game, date: game.release_date, platform: 'TapTap', url: game.source_url })),
    ...((data.value.haoyou?.days || []).flatMap((day) => (day.games || []).map((game) => ({
      ...game, date: haoyouReleaseDate(day.date, game.event_desc), platform: '好游快爆', url: game.detail_url,
    })))),
    ...((data.value.jiuyou?.days || []).flatMap((day) => (day.games || []).map((game) => ({
      ...game, date: day.date, platform: '九游', url: game.detail_url,
    })))),
    ...((data.value.p16?.days || []).flatMap((day) => (day.games || []).map((game) => ({
      ...game, date: game.release_date || day.date, platform: '游资网', url: game.detail_url,
    })))),
  ].filter((game) => game.has_afk_grinding_tag && game.date >= today && game.date < end)

  const games = new Map()
  for (const entry of entries) {
    const name = displayGameName(entry.game_name)
    const key = gameKey(name)
    if (!key) continue
    if (!games.has(key)) games.set(key, { name, dates: new Map() })
    const game = games.get(key)
    const dateEntry = game.dates.get(entry.date) || { date: entry.date, platforms: [], url: entry.url }
    if (!dateEntry.platforms.includes(entry.platform)) dateEntry.platforms.push(entry.platform)
    // 同一站点可能同时有预下载和正式上线两条，保留同日的一条即可。
    if (!dateEntry.url && entry.url) dateEntry.url = entry.url
    game.dates.set(entry.date, dateEntry)
  }
  return [...games.values()]
    .map((game) => {
      const dates = [...game.dates.values()].sort((a, b) => a.date.localeCompare(b.date))
      return { ...game, dates, url: dates.find((entry) => entry.url)?.url || '' }
    })
    .sort((a, b) => a.dates[0].date.localeCompare(b.dates[0].date) || a.name.localeCompare(b.name, 'zh-CN'))
})

// 首页概览以已完成采集的「昨天」为基准，避免当天滚动采集尚未完成造成误读。
const overview = computed(() => {
  const days = dailyNewsTrendData.value?.days || []
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date())
  const today = `${parts.find((part) => part.type === 'year').value}-${parts.find((part) => part.type === 'month').value}-${parts.find((part) => part.type === 'day').value}`
  const dateBefore = (date, offset) => new Date(Date.parse(`${date}T00:00:00Z`) + offset * 86400000).toISOString().slice(0, 10)
  const yesterdayDate = dateBefore(today, -1)
  const beforeDate = dateBefore(today, -2)
  const yesterday = days.find((day) => day.date === yesterdayDate)
  const before = days.find((day) => day.date === beforeDate)
  const sourceKeys = (dailyNewsTrendData.value?.sources || []).map((source) => source.key)
  const complete = (day) => sourceKeys.length > 0 && sourceKeys.every((key) => Number.isFinite(day?.counts?.[key]))
  const total = (day) => complete(day)
    ? sourceKeys.reduce((sum, key) => sum + day.counts[key], 0)
    : null
  const yesterdayTotal = yesterday ? total(yesterday) : null
  const beforeTotal = before ? total(before) : null
  const change = yesterdayTotal !== null && beforeTotal !== null ? yesterdayTotal - beforeTotal : null
  const weekStart = dateBefore(yesterdayDate, -6)
  const week = days.filter((day) => day.date >= weekStart && day.date <= yesterdayDate)
  const sourceTotals = new Map()
  const completeWeek = week.length === 7 && week.every(complete)
  if (completeWeek) for (const day of week) for (const [source, value] of Object.entries(day.counts || {})) sourceTotals.set(source, (sourceTotals.get(source) || 0) + value)
  const peakKey = completeWeek ? [...sourceTotals.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] : null
  const peak = dailyNewsTrendData.value?.sources?.find((source) => source.key === peakKey)?.label || '—'
  // 仅资讯 KPI 采用昨日口径；新游仍从北京时间今天起向未来看 7 天。
  const start = new Date(`${today}T00:00:00Z`)
  const end = new Date(start.getTime() + 7 * 86400000)
  const upcomingSources = [data.value.haoyou, data.value.jiuyou, data.value.p16]
  const upcomingComplete = upcomingSources.every((source) => Array.isArray(source?.days)) && Array.isArray(data.value.taptap)
  const upcomingDays = upcomingSources.flatMap((source) => source?.days || [])
  const scheduled = upcomingComplete ? upcomingDays.reduce((sum, day) => {
    const d = new Date(`${day.date || ''}T00:00:00Z`)
    return d >= start && d < end ? sum + (day.games?.length || 0) : sum
  }, 0) + (data.value.taptap || []).filter((game) => {
    const d = new Date(`${game.release_date || ''}T00:00:00Z`)
    return !Number.isNaN(d) && d >= start && d < end
  }).length : null
  const dynamics = Array.isArray(data.value.hot?.publishers)
    ? data.value.hot.publishers.reduce((sum, publisher) => sum + (publisher.games || []).reduce((n, game) => n + (game.updates?.length || 0), 0), 0)
    : null
  return { yesterdayTotal, change, peak, scheduled, dynamics, date: yesterday?.date || '—' }
})

const PAGE_NAMES = Object.fromEntries(SECTIONS)

// 导出使用浏览器原生生成的 SpreadsheetML 2003 XML：Excel 可直接打开 .xls，
// 且能写入多个工作表，无需在前端引入存在安全审计问题的第三方解析库。
// 行数据必须是扁平标量。保留嵌套字段内容为 JSON，避免导出时静默丢掉新闻、标签等信息。
function exportCell(value) {
  if (value === null || value === undefined) return ''
  if (typeof value !== 'object') return value
  return JSON.stringify(value)
}
function exportRows(rows) {
  const keys = [...new Set(rows.flatMap((row) => Object.keys(row || {})))]
  return rows.map((row) => Object.fromEntries(keys.map((key) => [key, exportCell(row?.[key])])) )
}
function fileTimestamp() {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
  }).formatToParts(new Date())
  const get = (type) => parts.find((part) => part.type === type)?.value || '00'
  return `${get('year')}${get('month')}${get('day')}-${get('hour')}${get('minute')}${get('second')}`
}
function safeSheetName(name, occupied) {
  const base = String(name).replace(/[\\/*?:\[\]]/g, '').slice(0, 31) || '数据'
  let candidate = base
  let suffix = 2
  while (occupied.has(candidate.toLocaleLowerCase())) {
    candidate = `${base.slice(0, 28)}-${suffix++}`
  }
  occupied.add(candidate.toLocaleLowerCase())
  return candidate
}
function downloadCurrentView() {
  const sheets = []
  const occupied = new Set()
  const addSheet = (name, rows) => {
    const values = exportRows(rows || [])
    sheets.push({ name: safeSheetName(name, occupied), rows: values.length ? values : [{ 状态: '暂无可导出数据' }] })
  }

  if (activeSection.value === 'weekly') {
    const weekly = data.value.weekly || {}
    addSheet('周报综述', [{
      周期开始: weekly.week_start, 周期结束: weekly.week_end, 文章数: weekly.article_count,
      游戏数: weekly.game_count, 综述: weekly.digest, 综述来源: weekly.digest_source,
      热度公式: weekly.heat_formula, 生成时间: weekly.generated_at,
    }])
    addSheet('综合热度榜', weekly.hot_ranking || [])
  } else if (activeSection.value === 'history') {
    const history = data.value.weeklyHistory || {}
    // 兼容尚未迁移的逐周旧数据：导出与页面一致，只保留每款游戏的历史最高热度。
    const bestHeatByName = new Map()
    for (const row of history.heat_ranking || []) {
      const previous = bestHeatByName.get(row.name)
      if (!previous || Number(row.heat_score) > Number(previous.heat_score) || (
        Number(row.heat_score) === Number(previous.heat_score)
        && (row.week_start || '') < (previous.week_start || '')
      )) bestHeatByName.set(row.name, row)
    }
    const heatRanking = [...bestHeatByName.values()]
      .sort((a, b) => Number(b.heat_score) - Number(a.heat_score) || Number(b.media_count) - Number(a.media_count) || a.name.localeCompare(b.name))
    // 热度榜是历史单游戏峰值，资讯榜是历史资讯累计；两个榜单始终分开写入工作表。
    addSheet('历史热度榜', heatRanking)
    addSheet('历史游戏资讯榜', history.news_ranking || [])
  } else if (activeSection.value === 'new-games') {
    addSheet('TapTap新游', data.value.taptap || [])
    for (const [label, payload] of [['好游快爆', data.value.haoyou], ['九游', data.value.jiuyou], ['游资网', data.value.p16]]) {
      addSheet(label, (payload?.days || []).flatMap((day) => (day.games || []).map((game) => ({ 日期: day.date, 日期说明: day.date_label, ...game }))))
    }
  } else if (activeSection.value === 'hot-games') {
    const publishers = data.value.hot?.publishers || []
    addSheet('厂商游戏概览', publishers.flatMap((publisher) => (publisher.games || []).map((game) => ({ 厂商: publisher.label, ...game, updates: undefined }))))
    // 厂商 Tab 分表，游戏和动态类型仍以列的形式完整保留，避免把不同抓取时间的内容混在一起。
    for (const publisher of publishers) {
      addSheet(`${publisher.label}动态`, (publisher.games || []).flatMap((game) => (game.updates || []).map((update) => ({ 游戏: game.game_name, 厂商: publisher.label, ...update }))))
    }
  } else if (activeSection.value === 'news') {
    for (const source of newsSources.value) {
      addSheet(`${source.label}新闻`, source.news?.items || [])
      addSheet(`${source.label}每日总结`, source.digest?.items || [])
      if (source.showReviews) addSheet(`${source.label}${source.reviewLabel || '评测'}`, source.reviews?.items || [])
    }
    const trendSources = dailyNewsTrendData.value?.sources || []
    addSheet('每日资讯趋势', (dailyNewsTrendData.value?.days || []).map((day) => {
      const complete = trendSources.length > 0 && trendSources.every((source) => Number.isFinite(day.counts?.[source.key]))
      return {
        日期: day.date,
        总量: complete ? trendSources.reduce((sum, source) => sum + day.counts[source.key], 0) : '数据不完整',
        ...(day.counts || {}),
      }
    }))
  }
  const escapeXml = (value) => String(value ?? '')
    .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&apos;')
  const sheetXml = sheets.map(({ name, rows }) => {
    const keys = Object.keys(rows[0] || {})
    const rowXml = [keys, ...rows.map((row) => keys.map((key) => row[key]))]
      .map((cells) => `<Row>${cells.map((cell) => `<Cell><Data ss:Type="String">${escapeXml(cell)}</Data></Cell>`).join('')}</Row>`).join('')
    return `<Worksheet ss:Name="${escapeXml(name)}"><Table>${rowXml}</Table></Worksheet>`
  }).join('')
  const workbook = `<?xml version="1.0" encoding="UTF-8"?><Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">${sheetXml}</Workbook>`
  const link = document.createElement('a')
  link.href = URL.createObjectURL(new Blob([workbook], { type: 'application/vnd.ms-excel;charset=utf-8' }))
  link.download = `${PAGE_NAMES[activeSection.value] || '竞品看板'}-${fileTimestamp()}.xls`
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(link.href), 0)
}

// 侧栏条目计数：让人在切板块之前就知道各板块有多少内容
const counts = computed(() => ({
  weekly: (data.value.weekly?.hot_ranking || []).length,
  history: (data.value.weeklyHistory?.heat_ranking || []).length,
  'new-games':
    (data.value.taptap || []).length +
    (data.value.haoyou?.days || []).reduce((n, d) => n + d.games.length, 0) +
    (data.value.jiuyou?.days || []).reduce((n, d) => n + d.games.length, 0) +
    (data.value.p16?.days || []).reduce((n, d) => n + d.games.length, 0),
  'hot-games': (data.value.hot?.publishers || []).reduce((n, p) => n + p.games.length, 0),
  news: newsSources.value.reduce((n, s) => n + (s.news?.items || []).length, 0),
}))

// 数据文件的生成时间字段并不统一：大部分采集结果放在顶层，TapTap 新游则在数组条目内。
// 只识别采集/生成/更新元数据，避免把文章发布时间误当成数据更新时间。
const TIMESTAMP_FIELDS = new Set(['crawled_at', 'generated_at', 'updated_at'])

function collectTimestamps(value, timestamps = []) {
  if (Array.isArray(value)) {
    value.forEach((item) => collectTimestamps(item, timestamps))
  } else if (value && typeof value === 'object') {
    Object.entries(value).forEach(([key, item]) => {
      if (TIMESTAMP_FIELDS.has(key) && typeof item === 'string') timestamps.push(item)
      else collectTimestamps(item, timestamps)
    })
  }
  return timestamps
}

// 顶栏总时间戳取当前成功加载的所有数据文件中最新的采集、生成或更新时间。
const newestStamp = computed(() => {
  const latest = collectTimestamps(Object.values(data.value))
    .map((iso) => ({ iso, time: new Date(iso).getTime() }))
    .filter(({ time }) => !Number.isNaN(time))
    .sort((a, b) => b.time - a.time)[0]
  if (!latest) return ''
  const d = new Date(latest.iso)
  const p = (n) => String(n).padStart(2, '0')
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
})

const NEWS_FILES = [
  '3dmgame_news.json', '3dmgame_reviews.json', '3dmgame_digest.json',
  'youxia_news.json', 'youxia_reviews.json', 'youxia_digest.json',
  'gamersky_news.json', 'gamersky_reviews.json', 'gamersky_digest.json',
  'gamelook_news.json', 'gamelook_digest.json',
  'gameres_news.json', 'gameres_digest.json',
  'daily_news_history.json',
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
      <section v-if="!loading" class="overview-card" aria-label="数据概览">
        <div class="overview-head"><h2>数据概览</h2><span class="stamp">统计截至 {{ overview.date }}</span><span class="spacer"></span><button class="icon-btn" @click="downloadCurrentView">导出当前页面 Excel</button></div>
        <div class="kpi-row">
          <div class="kpi"><div class="k">昨日资讯总量</div><div class="v">{{ overview.yesterdayTotal ?? '—' }}<small v-if="overview.yesterdayTotal !== null">条</small></div></div>
          <div class="kpi"><div class="k">较前日变化</div><div class="v" :class="{ positive: overview.change > 0, negative: overview.change < 0 }">{{ overview.change === null ? '—' : `${overview.change > 0 ? '+' : ''}${overview.change}` }}<small v-if="overview.change !== null">条</small></div></div>
          <div class="kpi"><div class="k">近 7 日峰值来源</div><div class="v compact-value">{{ overview.peak }}</div></div>
          <div class="kpi"><div class="k">未来 7 日新游</div><div class="v">{{ overview.scheduled ?? '—' }}<small v-if="overview.scheduled !== null">款</small></div></div>
          <div class="kpi"><div class="k">官方动态数</div><div class="v">{{ overview.dynamics ?? '—' }}<small v-if="overview.dynamics !== null">条</small></div></div>
          <div class="kpi"><div class="k">最新数据时间</div><div class="v compact-value">{{ newestStamp || '—' }}</div></div>
        </div>
        <section class="afk-upcoming" aria-label="未来七日可挂机或搬砖游戏">
          <div class="afk-upcoming-head">
            <h3>未来 7 日可挂机/搬砖游戏</h3>
            <span class="stamp">{{ afkUpcomingGames.length }} 款</span>
          </div>
          <p v-if="!afkUpcomingGames.length" class="afk-empty">暂无符合条件的游戏</p>
          <div v-else class="afk-game-list">
            <div v-for="game in afkUpcomingGames" :key="game.name" class="afk-game">
              <a v-if="game.url" class="afk-game-name" :href="game.url" target="_blank" rel="noopener noreferrer">{{ game.name }}</a>
              <span v-else class="afk-game-name">{{ game.name }}</span>
              <div class="afk-schedules">
                <div v-for="schedule in game.dates" :key="schedule.date" class="afk-schedule">
                  <time :datetime="schedule.date">{{ shortDate(schedule.date) }}</time>
                  <span>{{ schedule.platforms.join('、') }}</span>
                </div>
              </div>
            </div>
          </div>
        </section>
      </section>
      <nav class="rail">
        <div v-for="[key, label] in SECTIONS" :key="key" class="rail-group" :class="{ active: activeSection === key }">
          <div class="rail-btn">
            <button class="rail-main" :class="{ active: activeSection === key }" @click="selectSection(key)">
              <span>{{ label }}</span><span class="count">{{ counts[key] || '' }}</span>
            </button>
            <button class="rail-toggle" :class="{ expanded: expandedSection === key }" :aria-label="`展开${label}小标题`" :aria-expanded="expandedSection === key" @click="toggleSection(key)">›</button>
          </div>
          <div v-show="expandedSection === key" class="rail-subnav">
            <button
              v-for="[anchor, sublabel] in SECTION_NAV[key]"
              :key="anchor"
              :class="{ active: activeSubAnchor === anchor }"
              @click="jumpToSection(key, anchor)"
            >{{ sublabel }}</button>
          </div>
        </div>
      </nav>

      <main>
        <!-- 加载中用骨架屏占位，避免数据到位后整页跳动 -->
        <div v-if="loading" class="card">
          <div class="skel skel-line" style="width: 40%"></div>
          <div class="skel skel-line"></div>
          <div class="skel skel-line" style="width: 80%"></div>
        </div>

        <template v-else>
          <section id="weekly-content" v-show="activeSection === 'weekly'" class="card section-anchor">
            <div class="card-head sticky-heading">
              <h2>上周总览</h2>
              <span class="spacer"></span>
              <RefreshButton
                :files="['weekly_digest.json']"
                storage-key="weekly-digest"
                @refreshed="onRefreshed"
              />
            </div>
            <div id="weekly-overview"><WeeklyDigestPanel :data="data.weekly" :error="errors.weekly || ''" /></div>
          </section>

          <section id="new-games-content" v-show="activeSection === 'new-games'" class="card section-anchor">
            <div class="card-head sticky-heading">
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

          <section id="history-content" v-show="activeSection === 'history'" class="card section-anchor">
            <div class="card-head sticky-heading">
              <h2>历史数据</h2>
              <span class="spacer"></span>
              <RefreshButton
                :files="['weekly_history.json']"
                storage-key="weekly-history"
                @refreshed="onRefreshed"
              />
            </div>
            <HistoryDataPanel :data="data.weeklyHistory" :error="errors.weeklyHistory || ''" />
          </section>

          <section id="hot-games-content" v-show="activeSection === 'hot-games'" class="card section-anchor">
            <div class="card-head sticky-heading">
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

          <section id="news-content" v-show="activeSection === 'news'" class="card section-anchor">
            <div class="card-head sticky-heading">
              <h2>游戏资讯</h2>
              <span class="spacer"></span>
              <RefreshButton :files="NEWS_FILES" storage-key="game-news" @refreshed="onRefreshed" />
            </div>
            <GameNewsPanel :sources="newsSources" :active="activeSection === 'news'" />
            <DailyNewsTrend :data="dailyNewsTrendData" :error="dailyNewsTrendError" />
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
.overview-card { grid-column: 1 / -1; background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-lg); box-shadow: var(--shadow-1); padding: 16px 20px 4px; }
.overview-head { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }.overview-head h2 { margin: 0; font-size: 15px; }.overview-head .spacer { flex: 1; }
.kpi .positive { color: var(--ok); }.kpi .negative { color: var(--danger); }.kpi .compact-value { font-size: 16px; padding-top: 3px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.afk-upcoming { margin: 0 0 12px; border-top: 1px solid var(--border); padding-top: 12px; }
.afk-upcoming-head { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }.afk-upcoming-head h3 { margin: 0; font-size: 13px; }.afk-empty { margin: 0; color: var(--text-3); font-size: 13px; }
.afk-game-list { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 8px 14px; }
.afk-game { display: flex; align-items: flex-start; gap: 9px; min-width: 0; padding: 8px 10px; border: 1px solid var(--border); border-radius: var(--r-sm); background: var(--surface-2); }
.afk-game-name { flex: none; max-width: 46%; overflow: hidden; color: var(--brand); font-size: 13px; font-weight: 600; line-height: 1.5; text-decoration: none; text-overflow: ellipsis; white-space: nowrap; }.afk-game-name:hover, .afk-game-name:focus-visible { text-decoration: underline; }
.afk-schedules { display: grid; min-width: 0; gap: 3px; font-size: 12px; line-height: 1.5; color: var(--text-2); }.afk-schedule { display: flex; gap: 5px; min-width: 0; }.afk-schedule time { flex: none; color: var(--text-3); font-variant-numeric: tabular-nums; }.afk-schedule span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.rail {
  position: sticky;
  top: calc(var(--app-bar-h) + 24px);
  align-self: start;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 4px;
  background: var(--surface-glass);
  -webkit-backdrop-filter: var(--glass-blur);
  backdrop-filter: var(--glass-blur);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  box-shadow: var(--shadow-1);
}

@supports not ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
  .rail { background: var(--surface); }
}

.rail-btn {
  border: none;
  background: none;
  text-align: left;
  padding: 0;
  border-radius: var(--r-sm);
  font-size: 14px;
  font-family: var(--font);
  color: var(--text-2);
  cursor: var(--cursor-link), pointer;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  position: relative;
  transform-origin: center;
  transition: transform .12s ease, background .12s, color .12s, box-shadow .12s;
}

.rail-main {
  flex: 1;
  min-width: 0;
  border: none;
  border-radius: var(--r-sm);
  background: none;
  color: inherit;
  cursor: var(--cursor-link), pointer;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 9px 4px 9px 12px;
  font: inherit;
  text-align: left;
}
.rail-toggle {
  width: 30px;
  align-self: stretch;
  border: none;
  border-radius: var(--r-sm);
  background: none;
  color: var(--text-3);
  cursor: var(--cursor-link), pointer;
  font-size: 21px;
  line-height: 1;
  transition: transform .15s ease, color .12s, background .12s;
}
.rail-toggle:hover, .rail-toggle:focus-visible { color: var(--brand); background: var(--surface-2); }
.rail-toggle.expanded { transform: rotate(90deg); }
.rail-btn:has(.rail-main.active) { background: var(--brand-weak); color: var(--brand); font-weight: 600; }
.rail-subnav { display: grid; gap: 2px; padding: 3px 4px 6px 20px; }
.rail-subnav button { border: none; border-radius: var(--r-sm); background: none; color: var(--text-2); cursor: var(--cursor-link), pointer; padding: 6px 8px; font: 12px var(--font); text-align: left; }
.rail-subnav button:hover, .rail-subnav button:focus-visible { color: var(--brand); background: var(--brand-weak); }
.rail-subnav button.active { color: var(--brand); opacity: .68; font-weight: 600; }
.section-anchor { scroll-margin-top: calc(var(--app-bar-h) + 16px); }

.rail-btn:hover,
.rail-btn:focus-visible {
  transform: scale(var(--focus-scale));
  z-index: 1;
  background: var(--surface-2);
  color: var(--text);
  box-shadow: var(--shadow-1);
}
.rail-btn:focus-visible { outline: 2px solid var(--brand); outline-offset: 2px; }
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
  .overview-card { padding: 14px 14px 2px; }

  .rail {
    position: static;
    flex-direction: row;
    overflow-x: auto;
    border-radius: 999px;
    padding: 3px 4px;
  }

  .rail-group { flex: none; }
  .rail-btn { border-radius: 999px; white-space: nowrap; }
  .rail-main, .rail-toggle { border-radius: 999px; }
  .rail-subnav { position: absolute; z-index: 2; min-width: 150px; padding: 5px; border: 1px solid var(--border); border-radius: var(--r-sm); background: var(--surface); box-shadow: var(--shadow-1); }
}
</style>
