<script setup>
import { ref, computed, watch, nextTick } from 'vue'

const props = defineProps({
  newsData: {
    type: Object,
    default: null,
    // { crawled_at, window_days, items: [ {title, url, published_at, summary} ] }
    // game_name 由采集侧标注，四个资讯源都有该字段（未识别到游戏时为空）
  },
  reviewsData: {
    type: Object,
    default: null,
    // { crawled_at, window_days, items: [ {title, url, score, published_at, comment_count, author} ] }
    // 游侠网评测额外带 platforms（字符串数组）与 cover（暂不展示），且 comment_count / score 可能为 null
  },
  newsError: {
    type: String,
    default: '',
  },
  reviewsError: {
    type: String,
    default: '',
  },
  // 来源名与评测 Tab 文案由父组件传入：3DMGame 用「测评」，游侠网用「评测」，两边用词按各自习惯保留
  sourceName: {
    type: String,
    default: '',
  },
  reviewLabel: {
    type: String,
    default: '测评',
  },
  // 新闻 Tab 下的补充说明，由父组件按来源传入；不传则不显示（3DMGame 不需要）
  newsNote: {
    type: String,
    default: '',
  },
  // 某些来源（如 GameLook）只有新闻没有评测，此时传 false 隐藏评测 tab 与整个评测分支
  showReviews: {
    type: Boolean,
    default: true,
  },
  digestData: {
    type: Object,
    default: null,
    // { generated_at, source, window_days, top_n,
    //   items: [ {date, article_count, game_count, untagged_count, digest,
    //             digest_source,
    //             game_digests: [{name, count, summary, summary_source}]} ] }
    // 四个资讯源都生成，不传则新闻总结 tab 不出现
  },
  digestError: {
    type: String,
    default: '',
  },
  // 新闻总结 tab 的开关，与 showReviews 同一套逻辑：默认关闭，只有明确接入的来源打开
  showDigest: {
    type: Boolean,
    default: false,
  },
})

// 面板内部的「新闻 / 评测 / 总结」子 Tab，默认新闻
const activeTab = ref('news')

const newsItems = computed(() => props.newsData?.items || [])
const reviewItems = computed(() => props.reviewsData?.items || [])

// 日期筛选：起止两个下拉框构成一个连续区间，'' 只在无数据时出现
const startDate = ref('')
const endDate = ref('')

function dateOf(item) {
  return (item.published_at || '').slice(0, 10)
}

// 可选日期取数据里实际出现的日期，按倒序排列，并带上当日条数
const dateOptions = computed(() => {
  const counter = new Map()
  for (const item of newsItems.value) {
    const date = dateOf(item)
    if (!date) continue
    counter.set(date, (counter.get(date) || 0) + 1)
  }
  return [...counter.entries()]
    .map(([date, count]) => ({ date, count }))
    .sort((a, b) => (a.date < b.date ? 1 : -1))
})

// 只保留数据里真实存在的日期，倒序（新 → 旧）
const availableDates = computed(() => dateOptions.value.map((opt) => opt.date))

// 区间必须落在已有数据的日期内：数据刷新后把越界的选择收回到完整区间
watch(
  availableDates,
  (dates) => {
    if (!dates.length) {
      startDate.value = ''
      endDate.value = ''
      return
    }
    const newest = dates[0]
    const oldest = dates[dates.length - 1]
    if (!dates.includes(startDate.value)) startDate.value = oldest
    if (!dates.includes(endDate.value)) endDate.value = newest
  },
  { immediate: true },
)

// 两个下拉互相裁剪可选项，天然保证 起始 <= 结束，不需要额外纠正逻辑
const startOptions = computed(() =>
  dateOptions.value.filter((opt) => opt.date <= endDate.value),
)
const endOptions = computed(() =>
  dateOptions.value.filter((opt) => opt.date >= startDate.value),
)

const isFullRange = computed(() => {
  const dates = availableDates.value
  if (!dates.length) return true
  return endDate.value === dates[0] && startDate.value === dates[dates.length - 1]
})

const filteredNews = computed(() => {
  if (!startDate.value || !endDate.value) return newsItems.value
  return newsItems.value.filter((item) => {
    const date = dateOf(item)
    return date >= startDate.value && date <= endDate.value
  })
})

// 统计键：忽略空格与冒号差异，让「黑神话：钟馗」「黑神话钟馗」「GTA 6」「GTA6」
// 这类同名异写落到同一个键上。只用于统计，不改动条目里存的 game_name。
// 注意不做前缀合并（「黑神话」不并入「黑神话：钟馗」），前缀可能对应别的作品，
// 归错了统计就失真。
function statKey(name) {
  return name.replace(/[\s:：]/g, '').toLowerCase()
}

// 只在区间收窄到单日时统计当日新闻数最多的 3 个游戏，并列时按展示名升序
const topGames = computed(() => {
  if (!startDate.value || startDate.value !== endDate.value) return []
  const groups = new Map()
  for (const item of filteredNews.value) {
    const name = item.game_name
    if (!name) continue
    const key = statKey(name)
    if (!key) continue
    let group = groups.get(key)
    if (!group) {
      group = { count: 0, variants: new Map() }
      groups.set(key, group)
    }
    group.count += 1
    group.variants.set(name, (group.variants.get(name) || 0) + 1)
  }
  return [...groups.values()]
    .map(({ count, variants }) => ({
      // 展示组内出现次数最多的完整写法，同样次数时取更长的（信息更全）
      name: [...variants.entries()].sort(
        (a, b) => b[1] - a[1] || b[0].length - a[0].length || (a[0] < b[0] ? -1 : 1)
      )[0][0],
      count
    }))
    .sort((a, b) => b.count - a.count || (a.name < b.name ? -1 : 1))
    .slice(0, 3)
})


const newsListRef = ref(null)

function resetRange() {
  const dates = availableDates.value
  if (!dates.length) return
  startDate.value = dates[dates.length - 1]
  endDate.value = dates[0]
}

// 换日期后列表内容整体变化，滚动位置需要回到顶部
watch([startDate, endDate], () => {
  nextTick(() => {
    if (newsListRef.value) newsListRef.value.scrollTop = 0
  })
})

function formatCrawledAt(isoString) {
  if (!isoString) return ''
  const d = new Date(isoString)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

// published_at 是采集侧输出的 'YYYY-MM-DD HH:mm:ss' 文本，直接截取避免时区偏移
function shortDate(date) {
  return (date || '').slice(5, 10)
}

function formatPublishedShort(published) {
  return (published || '').slice(5, 16)
}

function formatPublishedFull(published) {
  return (published || '').slice(0, 16)
}

function scoreClass(score) {
  const value = Number(score)
  if (!score || Number.isNaN(value)) return 'score-none'
  if (value >= 9) return 'score-high'
  if (value >= 8) return 'score-good'
  if (value >= 7) return 'score-fair'
  return 'score-low'
}

function scoreText(score) {
  return score ? score : '暂无评分'
}

// 空态带上窗口天数，避免只显示一片空白让人误以为是加载失败
const newsEmptyText = computed(() => {
  const days = props.newsData?.window_days
  return days ? `近 ${days} 天暂无新闻` : '暂无数据'
})

const reviewsEmptyText = computed(() => {
  const days = props.reviewsData?.window_days
  return days ? `近 ${days} 天暂无${props.reviewLabel}` : '暂无数据'
})

// ---- 总结 tab ----
// 总结按天生成，一天一条，脚本已按日期倒序写好，这里不再排序
const digestItems = computed(() => props.digestData?.items || [])

// 总结用单日选择（和新闻的起止区间是两套独立状态，互不影响）
const digestDate = ref('')

const digestDates = computed(() => digestItems.value.map((entry) => entry.date))

// 数据刷新后日期可能整体后移，选中项越界就回到最新一天
watch(
  digestDates,
  (dates) => {
    if (!dates.length) {
      digestDate.value = ''
      return
    }
    if (!dates.includes(digestDate.value)) digestDate.value = dates[0]
  },
  { immediate: true },
)

const currentDigest = computed(
  () => digestItems.value.find((entry) => entry.date === digestDate.value) || null,
)

const digestTopN = computed(() => props.digestData?.top_n || 15)

// 兼容早期只写了 top_games 的旧数据：那时没有单游戏总结，退化成只显示名字和条数
const currentGameDigests = computed(() => {
  const entry = currentDigest.value
  if (!entry) return []
  if (entry.game_digests?.length) return entry.game_digests
  return (entry.top_games || []).map((g) => ({ ...g, summary: '' }))
})

const digestEmptyText = computed(() => {
  const days = props.digestData?.window_days
  return days ? `近 ${days} 天暂无总结` : '暂无数据'
})


</script>

<template>
  <div class="news-panel">
    <nav v-if="showReviews || showDigest" class="tab-nav">
      <button
        :class="['tab-btn', { active: activeTab === 'news' }]"
        @click="activeTab = 'news'"
      >新闻</button>
      <button
        v-if="showDigest"
        :class="['tab-btn', { active: activeTab === 'digest' }]"
        @click="activeTab = 'digest'"
      >新闻总结</button>
      <button
        v-if="showReviews"
        :class="['tab-btn', { active: activeTab === 'reviews' }]"
        @click="activeTab = 'reviews'"
      >{{ reviewLabel }}</button>

    </nav>

    <section v-if="activeTab === 'news' || (!showReviews && !showDigest)" class="tab-section">
      <p v-if="newsError" class="error">{{ newsError }}</p>
      <template v-else>
        <div v-if="newsData" class="panel-meta">
          <div class="source-line">
            {{ sourceName }} 新闻：近 {{ newsData.window_days }} 天 · 更新于 {{ formatCrawledAt(newsData.crawled_at) }}

          </div>
        </div>

        <p v-if="newsNote" class="news-note">{{ newsNote }}</p>

        <div v-if="dateOptions.length" class="pub-nav">
          <label class="date-field">
            起始
            <select v-model="startDate" class="date-select">
              <option v-for="opt in startOptions" :key="opt.date" :value="opt.date">
                {{ shortDate(opt.date) }}（{{ opt.count }}）
              </option>
            </select>
          </label>
          <span class="range-sep">至</span>
          <label class="date-field">
            结束
            <select v-model="endDate" class="date-select">
              <option v-for="opt in endOptions" :key="opt.date" :value="opt.date">
                {{ shortDate(opt.date) }}（{{ opt.count }}）
              </option>
            </select>
          </label>
          <span class="range-count">共 {{ filteredNews.length }} 条</span>
          <button v-if="!isFullRange" class="reset-btn" @click="resetRange">全部日期</button>
        </div>

        <p v-if="topGames.length" class="top-games">
          当日热点：<span
            v-for="(g, i) in topGames"
            :key="g.name"
          >{{ i > 0 ? ' · ' : '' }}{{ g.name }}（{{ g.count }}）</span>
        </p>

        <p v-if="filteredNews.length === 0" class="empty">{{ newsEmptyText }}</p>

        <ul v-else ref="newsListRef" class="news-list">
          <li v-for="(item, i) in filteredNews" :key="item.url || i" class="news-item">
            <div class="item-head">
              <span v-if="item.game_name" class="game-tag">{{ item.game_name }}</span>
              <span class="item-date">{{ formatPublishedShort(item.published_at) }}</span>
            </div>
            <a
              v-if="item.url"
              class="item-title"
              :href="item.url"
              target="_blank"
              rel="noopener"
            >{{ item.title }}</a>
            <span v-else class="item-title">{{ item.title }}</span>
            <p v-if="item.summary" class="item-summary">{{ item.summary }}</p>
          </li>
        </ul>
      </template>
    </section>

    <section v-if="activeTab === 'reviews' && showReviews" class="tab-section">
      <p v-if="reviewsError" class="error">{{ reviewsError }}</p>
      <template v-else>
        <div v-if="reviewsData" class="panel-meta">
          <div class="source-line">
            {{ sourceName }} {{ reviewLabel }}：近 {{ reviewsData.window_days }} 天 · 更新于 {{ formatCrawledAt(reviewsData.crawled_at) }}

          </div>
        </div>

        <p v-if="reviewItems.length === 0" class="empty">{{ reviewsEmptyText }}</p>

        <ul v-else class="review-list">
          <li v-for="(item, i) in reviewItems" :key="item.url || i" class="review-item">
            <span :class="['score-badge', scoreClass(item.score)]">{{ scoreText(item.score) }}</span>
            <div class="review-body">
              <a
                v-if="item.url"
                class="item-title"
                :href="item.url"
                target="_blank"
                rel="noopener"
              >{{ item.title }}</a>
              <span v-else class="item-title">{{ item.title }}</span>
              <div class="review-meta">
                <span>{{ formatPublishedFull(item.published_at) }}</span>
                <span v-if="item.author" class="review-author">by {{ item.author }}</span>
                <span v-if="item.comment_count !== null && item.comment_count !== undefined">评论 {{ item.comment_count }}</span>
                <span
                  v-for="p in (item.platforms || [])"
                  :key="p"
                  class="platform-tag"
                >{{ p }}</span>
              </div>

            </div>
          </li>
        </ul>
      </template>
    </section>

    <section v-if="activeTab === 'digest' && showDigest" class="tab-section">
      <p v-if="digestError" class="error">{{ digestError }}</p>
      <template v-else>
        <div v-if="digestData" class="panel-meta">
          <div class="source-line">
            {{ sourceName }} 每日新闻总结：近 {{ digestData.window_days }} 天 · 更新于 {{ formatCrawledAt(digestData.generated_at) }}
          </div>
        </div>

        <div v-if="digestDates.length" class="pub-nav">
          <label class="date-field">
            日期
            <select v-model="digestDate" class="date-select">
              <option v-for="entry in digestItems" :key="entry.date" :value="entry.date">
                {{ shortDate(entry.date) }}（{{ entry.article_count }}）
              </option>
            </select>
          </label>
          <span v-if="currentDigest" class="range-count">
            {{ currentDigest.article_count }} 条 · {{ currentDigest.game_count }} 款游戏
          </span>
        </div>

        <p v-if="!currentDigest" class="empty">{{ digestEmptyText }}</p>

        <template v-else>
          <p class="digest-text">{{ currentDigest.digest }}</p>

          <p class="digest-subhead">各游戏当日动态（Top {{ digestTopN }}）</p>
          <ol v-if="currentGameDigests.length" class="digest-game-list">
            <li v-for="g in currentGameDigests" :key="g.name" class="digest-game-item">
              <p class="digest-game-head">
                <span class="digest-game">{{ g.name }}</span>
                <span class="digest-count">{{ g.count }} 条</span>
              </p>
              <p class="digest-game-summary">{{ g.summary }}</p>
            </li>
          </ol>
          <p v-else class="empty">当日没有指向具体游戏的新闻</p>
        </template>
      </template>
    </section>
  </div>
</template>

<style scoped>
.tab-nav {
  display: flex;
  gap: 6px;
  margin-bottom: 12px;
}

.tab-btn {
  border: 1px solid #ddd;
  background: #fff;
  padding: 6px 16px;
  border-radius: 16px;
  font-size: 13px;
  cursor: pointer;
  color: #333;
}

.tab-btn:hover {
  border-color: #1976d2;
  color: #1976d2;
}

.tab-btn.active {
  background: #1976d2;
  color: #fff;
  border-color: #1976d2;
}

.panel-meta {
  font-size: 12px;
  margin-bottom: 8px;
}

.panel-meta .source-line {
  color: #666;
}

/* 说明性小字，字号/颜色沿用 .panel-meta 与 .empty 的弱化风格，长文本自动换行不截断 */
.news-note {
  margin: 0 0 8px;
  font-size: 12px;
  color: #999;
  line-height: 1.6;
  word-break: break-word;
}

.pub-nav {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 8px 0;
  margin-bottom: 12px;
  border-bottom: 1px solid #eee;
}

.date-field {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  color: #666;
}

.date-select {
  border: 1px solid #ddd;
  border-radius: 4px;
  background: #fff;
  padding: 5px 8px;
  font-size: 13px;
  color: #333;
  cursor: pointer;
}

.date-select:hover {
  border-color: #1976d2;
}

.range-sep {
  font-size: 13px;
  color: #999;
}

.range-count {
  font-size: 12px;
  color: #999;
}

.reset-btn {
  border: 1px solid #ddd;
  background: #fff;
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 12px;
  cursor: pointer;
  color: #666;
}

.reset-btn:hover {
  border-color: #1976d2;
  color: #1976d2;
}

.top-games {
  margin: 0 0 12px;
  font-size: 13px;
  color: #444;
}

.empty {
  color: #999;
  font-size: 13px;
}

.error {
  color: #d32f2f;
  font-size: 13px;
}

/* 新闻条数多，限高在列表内滚动，避免把整页拉长。
   373px 是刻意压缩的结果（原 560px 的 2/3），配合更紧的 gap / padding-top
   让四个来源卡片在一屏内的占位更均衡，不是随手写的魔法数字，调整前请确认视觉预期。 */
.news-list {
  list-style: none;
  margin: 0;
  padding: 0 6px 0 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 373px;
  overflow-y: auto;
  /* 到顶/到底后允许滚动链接到整页 */
  overscroll-behavior: auto;
}

.news-list::-webkit-scrollbar {
  width: 6px;
}

.news-list::-webkit-scrollbar-thumb {
  background: #d0d0d0;
  border-radius: 3px;
}

.news-list::-webkit-scrollbar-thumb:hover {
  background: #b0b0b0;
}

.news-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  border-top: 1px solid #f0f0f0;
  padding-top: 6px;
}

.news-item:first-child {
  border-top: none;
  padding-top: 0;
}

.item-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.game-tag {
  font-size: 12px;
  padding: 1px 6px;
  border-radius: 3px;
  color: #fff;
  background: #546e7a;
  flex-shrink: 0;
}

.item-date {
  font-size: 12px;
  color: #999;
}

.item-title {
  font-size: 13px;
  color: #222;
  line-height: 1.4;
  text-decoration: none;
  font-weight: 600;
}

a.item-title:hover {
  color: #1976d2;
  text-decoration: underline;
}

/* 摘要较长，统一裁到 2 行保证列表节奏一致 */
.item-summary {
  margin: 0;
  font-size: 12px;
  color: #666;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
}

.review-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.review-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  border-top: 1px solid #f0f0f0;
  padding-top: 12px;
}

.review-item:first-child {
  border-top: none;
  padding-top: 0;
}

.score-badge {
  flex-shrink: 0;
  min-width: 46px;
  text-align: center;
  padding: 4px 8px;
  border-radius: 4px;
  color: #fff;
  font-size: 14px;
  font-weight: bold;
}

.score-high {
  background: #2e7d32;
}

.score-good {
  background: #1976d2;
}

.score-fair {
  background: #ef6c00;
}

.score-low,
.score-none {
  background: #757575;
}

.score-none {
  font-size: 12px;
  font-weight: normal;
}

.review-body {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.review-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 12px;
  color: #999;
}

.review-author {
  color: #666;
}

.platform-tag {
  padding: 1px 6px;
  border-radius: 3px;
  color: #fff;
  background: #78909c;
}

/* 综述是一整段连续文字，行高比列表项松一档，读起来不费劲 */
.digest-text {
  margin: 0 0 16px;
  font-size: 13px;
  color: #333;
  line-height: 1.8;
  text-align: justify;
}

.digest-subhead {
  margin: 0 0 8px;
  font-size: 13px;
  font-weight: 600;
  color: #444;
}

/* 每款游戏一段总结，长度不定，只能单列竖排；靠间距区分条目，不加边框省得太重 */
.digest-game-list {
  margin: 0;
  padding-left: 22px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.digest-game-item {
  font-size: 13px;
  color: #333;
}

.digest-game-head {
  margin: 0 0 2px;
  font-weight: 600;
}

.digest-game-summary {
  margin: 0;
  font-weight: 400;
  line-height: 1.75;
  color: #444;
  text-align: justify;
}

.digest-game {
  margin-right: 6px;
}

.digest-count {
  font-size: 12px;
  font-weight: 400;
  color: #999;
}

</style>
