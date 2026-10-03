<script setup>
import { computed, ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import ClampedSummary from './ClampedSummary.vue'
const props = defineProps({ detail: { type: Object, default: null }, loading: Boolean })
defineEmits(['back'])
const source = ref('')
const type = ref('')
const page = ref(1)
const copyStatus = ref('')
const titleSentinel = ref(null)
const titleCompact = ref(false)
let titleFrame = null
function updateTitle() {
  titleFrame = null
  if (!titleSentinel.value) { titleCompact.value = false; return }
  const top = document.querySelector('.app-bar')?.getBoundingClientRect().height || 56
  // 每帧读取实际位置：1px 哨兵在慢速进入视口时，IntersectionObserver
  // 可能在标题尚未离开吸顶线前触发一次，之后不再通知，导致缩小状态滞留。
  titleCompact.value = window.scrollY > 0 && titleSentinel.value.getBoundingClientRect().bottom <= top
}
function scheduleTitleUpdate() {
  if (titleFrame === null) titleFrame = window.requestAnimationFrame(updateTitle)
}
onMounted(() => {
  window.addEventListener('scroll', scheduleTitleUpdate, { passive: true })
  window.addEventListener('resize', scheduleTitleUpdate)
  nextTick(scheduleTitleUpdate)
})
watch(() => props.detail?.key, () => nextTick(scheduleTitleUpdate))
onUnmounted(() => {
  window.removeEventListener('scroll', scheduleTitleUpdate)
  window.removeEventListener('resize', scheduleTitleUpdate)
  if (titleFrame !== null) window.cancelAnimationFrame(titleFrame)
})
const sources = [['3dm', '3DM'], ['youxia', '游侠'], ['gamersky', '游民'], ['gamelook', 'GameLook'], ['gameres', '游资']]
const filtered = computed(() => (props.detail?.articles || []).filter(a => (!source.value || a.source === source.value) && (!type.value || a.type === type.value)))
const pageSize = 10
const pages = computed(() => Math.max(1, Math.ceil(filtered.value.length / pageSize)))
const articles = computed(() => filtered.value.slice((page.value - 1) * pageSize, page.value * pageSize))
const pageOptions = computed(() => {
  const visible = new Set([1, pages.value, page.value - 2, page.value - 1, page.value, page.value + 1, page.value + 2])
  const ordered = [...visible].filter(value => value >= 1 && value <= pages.value).sort((a, b) => a - b)
  return ordered.reduce((options, value, index) => {
    if (index && value - ordered[index - 1] > 1) options.push(null)
    options.push(value)
    return options
  }, [])
})
watch([source, type, () => props.detail?.key], () => { page.value = 1 })
watch(pages, value => { page.value = Math.min(page.value, value) })
const weekly = computed(() => props.detail?.history?.latestWeekly)
const peak = computed(() => props.detail?.history?.peakWeekly)
const cumulative = computed(() => props.detail?.history?.cumulativeNews)
function period(row) { return [row?.week_start, row?.week_end].filter(Boolean).join(' ~ ') || '周期未提供' }
function labelType(value) { return ({news:'新闻', review:'评测'})[value] || value }
function range(row) { return [row?.first_article_date, row?.last_article_date].filter(Boolean).join(' ~ ') || '日期范围未提供' }
async function copyLink() {
  try { await navigator.clipboard.writeText(window.location.href); copyStatus.value = '详情链接已复制' }
  catch { copyStatus.value = '复制未成功，请复制地址栏中的详情链接' }
}
const states = computed(() => props.detail?.sourceStates || [])
function relevantStates(section) {
  return states.value.filter(s => section === 'articles' ? /News|Reviews/.test(s.key) && (!source.value || s.source === source.value) && (!type.value || (type.value === 'news' ? /News$/.test(s.key) : /Reviews$/.test(s.key))) : section === 'official' ? s.key === 'hot' || s.key?.startsWith('official') : section === 'weekly' ? s.key === 'weekly' : section === 'history' ? s.key === 'weeklyHistory' : ['taptap','haoyou','jiuyou','p16'].includes(s.key))
}
function incomplete(section) { return relevantStates(section).some(s => s.status !== 'ok') }
function countLabel(section, count) { return incomplete(section) ? count ? `${count}（部分）` : '不可用 / 未收录' : count }
function jump(event) { event.preventDefault(); document.getElementById(event.currentTarget.hash.slice(1))?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }
function emptyText(section) {
  return incomplete(section) ? '相关来源异常或尚不可用；当前可用数据中暂无，请查看来源状态' : '当前收录范围内暂无'
}
</script>

<template>
  <section class="game-detail">
    <div class="detail-toolbar"><button class="icon-btn" @click="$emit('back')">← 返回原列表</button><slot name="actions" /><button class="icon-btn" @click="copyLink">复制详情链接</button></div>
    <p role="status" class="hint">{{ copyStatus }}</p>
    <p v-if="loading" class="state">正在加载游戏数据…</p>
    <div v-else-if="!detail" class="state"><h1 data-game-detail-heading tabindex="-1">当前数据中未找到该游戏</h1><p>可返回列表查看当前收录的游戏。</p></div>
    <template v-else>
      <div ref="titleSentinel" class="title-sentinel" aria-hidden="true"></div><h1 class="detail-title" :class="{ compact: titleCompact }" data-game-detail-heading tabindex="-1">{{ detail.name }}</h1>
      <p v-if="detail.aliases?.length" class="hint">名称关联：{{ detail.aliases.join(' / ') }}</p>
      <div class="detail-profiles">
        <div v-for="(profile, i) in detail.profiles" :key="i" class="profile">
          <strong>{{ profile.sourceLabel }}</strong>
          <span v-if="profile.publisher">发行商：{{ profile.publisher }}</span>
          <span v-if="profile.categories?.length">分类：{{ profile.categories.join('、') }}</span>
          <span v-if="profile.platforms?.length">运行平台：{{ profile.platforms.join('、') }}</span>
          <span v-if="profile.score != null && profile.score !== ''">该来源评分：{{ profile.score }}</span>
          <span v-if="profile.reservation_count">该来源预约：{{ profile.reservation_count }}</span>
          <span v-if="profile.follow_count">该来源关注：{{ profile.follow_count }}</span>
        </div>
      </div>
      <nav class="detail-links" aria-label="游戏官网及来源"><a v-for="(link, i) in detail.links" :key="i" :href="link.url" target="_blank" rel="noopener noreferrer">{{ link.label || link.sourceLabel }} ↗</a></nav>
      <p class="hint">当前收录资讯：新闻通常保留最近 10 天，评测 15 天，官方动态 7 天。历史统计不等于完整历史原文；所有日期按北京时间展示。</p>
      <details class="source-states"><summary>数据覆盖与来源状态（{{ states.filter(s => s.status === 'error').length }} 项异常）</summary><ul><li v-for="(state, i) in states" :key="i" :class="{ 'source-error': state.status === 'error' }">{{ state.label || state.sourceLabel }}：{{ state.status === 'error' ? `来源异常 · ${state.error || '采集失败'}` : state.status === 'missing' ? '尚未提供数据' : '加载成功' }}<span v-if="state.crawledAt"> · {{ state.crawledAt }}</span></li></ul></details>
      <div class="detail-stats"><a href="#game-detail-articles" @click="jump">当前收录资讯 <strong>{{ countLabel('articles', detail.articles.length) }}</strong></a><a href="#game-detail-official" @click="jump">官方动态 <strong>{{ countLabel('official', detail.officialUpdates.length) }}</strong></a><a href="#game-detail-schedules" @click="jump">排期记录 <strong>{{ countLabel('schedules', detail.schedules.length) }}</strong></a><a href="#game-detail-history" @click="jump">历史累计资讯 <strong>{{ cumulative?.media_count ?? '—' }}</strong></a></div>

      <section id="game-detail-articles"><h2>跨站资讯</h2><div class="detail-filters"><label>来源 <select v-model="source"><option value="">全部来源</option><option v-for="[key, label] in sources" :key="key" :value="key">{{ label }}</option></select></label><label>类型 <select v-model="type"><option value="">全部类型</option><option value="news">新闻</option><option value="review">评测</option></select></label></div>
        <p v-if="!articles.length" class="state">{{ filtered.length ? '' : emptyText('articles') }}</p>
        <ul v-else class="detail-records"><li v-for="(article, i) in articles" :key="article.url || i"><div class="record-meta">{{ article.date || '日期未提供' }} · {{ article.sourceLabel }} · {{ labelType(article.type) }}</div><h3>{{ article.title }}</h3><ClampedSummary v-if="article.summary" :text="article.summary" /><a v-if="article.url" :href="article.url" target="_blank" rel="noopener noreferrer">查看原文 ↗</a></li></ul>
        <nav v-if="pages > 1" class="detail-pager" aria-label="游戏资讯分页">
          <button class="icon-btn" :disabled="page === 1" @click="page--">上一页</button>
          <template v-for="(value, index) in pageOptions" :key="value || `gap-${index}`">
            <span v-if="value === null" class="pager-gap" aria-hidden="true">…</span>
            <button v-else class="icon-btn pager-page" :class="{ active: value === page }" :aria-current="value === page ? 'page' : null" :aria-label="`第 ${value} 页`" @click="page = value">{{ value }}</button>
          </template>
          <button class="icon-btn" :disabled="page === pages" @click="page++">下一页</button>
        </nav>
      </section>
      <section id="game-detail-official"><h2>官方动态</h2><p v-if="incomplete('official')" class="source-error">官方来源异常或待接入，当前动态可能不完整。</p><p v-if="!detail.officialUpdates.length" class="state">{{ emptyText('official') }}</p><ul v-else class="detail-records"><li v-for="(update, i) in detail.officialUpdates" :key="update.url || i"><div class="record-meta">{{ update.date || '日期未提供' }} · {{ update.sourceLabel }} · {{ update.type }}</div><h3>{{ update.title }}</h3><p v-if="update.summary">{{ update.summary }}</p><a v-if="update.url" :href="update.url" target="_blank" rel="noopener noreferrer">查看原文 ↗</a></li></ul></section>
      <section id="game-detail-schedules"><h2>上线与测试排期</h2><p class="hint">不同日期或事件类型分别保留。来源日期差异不代表延期。</p><p v-if="!detail.schedules.length" class="state">{{ emptyText('schedules') }}</p><ul v-else class="detail-records"><li v-for="(schedule, i) in detail.schedules" :key="i"><h3>{{ schedule.date || '日期未提供' }} · {{ schedule.type }}</h3><div v-for="(entry, j) in schedule.sources" :key="j">{{ entry.sourceLabel }} <span v-if="entry.event_desc">· {{ entry.event_desc }}</span> <a v-if="entry.url" :href="entry.url" target="_blank" rel="noopener noreferrer">查看详情 ↗</a></div></li></ul></section>
      <section id="game-detail-history"><h2>已有历史记录</h2><div class="history-stats"><div><h3>上周热度与排名</h3><template v-if="weekly"><strong>{{ weekly.heat_score }} · 第 {{ weekly.rank }} 名</strong><p>{{ period(weekly) }}</p></template><p v-else>{{ emptyText('weekly') }}</p></div><div><h3>历史最高周热度</h3><template v-if="peak"><strong>{{ peak.heat_score }}</strong><p>{{ period(peak) }}</p></template><p v-else>{{ emptyText('history') }}</p></div><div><h3>历史累计资讯</h3><template v-if="cumulative"><template v-if="!cumulative.separateRecords"><strong>{{ cumulative.media_count }} 条</strong><p>{{ range(cumulative) }}</p></template><template v-else><p>别名记录缺少可靠去重标识，分别展示：</p><p v-for="(row, i) in cumulative.records" :key="i">{{ row.name }}：{{ row.media_count }} 条 · {{ range(row) }}</p></template></template><p v-else>{{ emptyText('history') }}</p></div></div><p class="hint">现有记录仅提供上周统计与历史峰值，无法绘制连续周热度曲线。</p></section>
    </template>
  </section>
</template>

<style scoped>
.game-detail { padding: 20px; border: 1px solid var(--border); border-radius: var(--r-md); background: var(--surface); }
.detail-toolbar,.detail-links,.detail-filters,.detail-pager { display:flex; flex-wrap:wrap; gap:12px; align-items:center; }.detail-toolbar { justify-content:space-between; }
h1 { font-size:28px; margin:12px 0; overflow-wrap:anywhere; } h2 { font-size:20px; margin:0 0 14px; } h3 { font-size:15px; margin:8px 0; }
.title-sentinel { height: 1px; margin-top: 12px; }
.detail-title { position: sticky; top: var(--app-bar-h); z-index: 12; margin: 0 0 12px; padding: 10px 0; line-height: 36px; background: var(--surface); transition: font-size .22s ease, box-shadow .22s ease; }
.detail-title.compact { font-size: 24px; box-shadow: 0 1px 0 var(--border); }
.detail-profiles { display:grid; gap:8px; margin:16px 0; }.profile { display:flex; flex-wrap:wrap; gap:8px 18px; font-size:13px; color:var(--text-2); }
.detail-links { margin:12px 0; }.source-states { font-size:13px; color:var(--text-2); margin:16px 0; }.source-states summary { cursor:pointer; }.source-states li { margin:6px 0; overflow-wrap:anywhere; }.source-error { color:var(--warn); }
.detail-stats,.history-stats { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin:20px 0; }.detail-stats a,.history-stats>div { border:1px solid var(--border); padding:14px; border-radius:var(--r-sm); }.detail-stats a { font-size:13px; text-decoration:none; }.detail-stats strong { display:block; margin-top:8px; font-size:24px; }.history-stats { grid-template-columns:repeat(3,minmax(0,1fr)); }.history-stats p { font-size:13px; color:var(--text-2); }
.game-detail section { margin-top:28px; scroll-margin-top:calc(var(--app-bar-h) + 72px); }.detail-filters select { margin-left:6px; padding:6px; border:1px solid var(--border); border-radius:var(--r-sm); background:var(--surface); color:var(--text); }.detail-records { list-style:none; padding:0; margin:14px 0; }.detail-records li { padding:16px 0; border-bottom:1px solid var(--border); overflow-wrap:anywhere; }.record-meta { font-size:12px; color:var(--text-3); }.detail-records p { color:var(--text-2); font-size:13px; line-height:1.6; }.detail-records a { font-size:13px; }.detail-pager { justify-content:center; font-size:13px; }
@media(max-width:680px) { .game-detail { padding:14px; }.detail-stats { grid-template-columns:repeat(2,minmax(0,1fr)); }.history-stats { grid-template-columns:1fr; } h1 { font-size:24px; } }
@media(max-width:680px) { .detail-title { font-size: 24px; }.detail-title.compact { font-size: 21px; } }
@media(prefers-reduced-motion:reduce) { .detail-title { transition: none; } }
.detail-pager { justify-content: flex-end; gap: 6px; margin-top: 12px; }
.detail-pager .icon-btn { height: 28px; padding: 0 9px; font-size: 12px; }
.detail-pager .pager-page { min-width: 28px; justify-content: center; padding: 0 6px; }
.detail-pager .pager-page.active { border-color: var(--brand); background: var(--brand-weak); color: var(--brand); }
.pager-gap { color: var(--text-3); line-height: 28px; }
</style>
