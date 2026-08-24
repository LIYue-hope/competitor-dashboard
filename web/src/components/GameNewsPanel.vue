<script setup>
import { ref, computed, watch } from 'vue'
import { useStickyTabs } from '../composables/useStickyTabs.js'

// 四个资讯源改成一级 Tab（原来是竖着堆四张卡，每张卡里再套一个限高滚动列表）。
// 每个 source 由 App 组装：
// { key, label, reviewLabel, showReviews, note,
//   news, reviews, digest, newsError, reviewsError, digestError }
const props = defineProps({
  sources: { type: Array, default: () => [] },
  active: { type: Boolean, default: false },
})

const stackRef = ref(null)
const rootRef = ref(null)
const activeRef = computed(() => props.active)
const { compact, remeasure } = useStickyTabs(stackRef, rootRef, activeRef)

const sourceKey = ref('')
const tab = ref('news')
const q = ref('')
// 新闻列表用起止区间，每日总结用单日，两套状态互不影响
const from = ref('')
const to = ref('')
const digestDate = ref('')

const src = computed(() => props.sources.find((s) => s.key === sourceKey.value) || props.sources[0] || null)

const TABS = computed(() => {
  const t = [['news', '新闻'], ['digest', '每日总结']]
  if (src.value?.showReviews) t.push(['reviews', src.value.reviewLabel || '测评'])
  return t
})

const activeTab = computed(() =>
  tab.value === 'reviews' && !src.value?.showReviews ? 'news' : tab.value,
)

function selectSource(key) {
  sourceKey.value = key
  q.value = ''
  from.value = ''
  to.value = ''
  digestDate.value = ''
}

watch([sourceKey, tab, q, from, to, digestDate], () => remeasure())

/* ---- 新闻 ---- */
const newsItems = computed(() => src.value?.news?.items || [])

const dateCounts = computed(() => {
  const m = new Map()
  for (const it of newsItems.value) {
    const d = (it.published_at || '').slice(0, 10)
    if (d) m.set(d, (m.get(d) || 0) + 1)
  }
  return m
})

const dates = computed(() => [...dateCounts.value.keys()].sort().reverse()) // 新 → 旧
const newest = computed(() => dates.value[0] || '')
const oldest = computed(() => dates.value[dates.value.length - 1] || '')

// 选中值越界（换来源、数据刷新）就收回到完整区间
const rangeFrom = computed(() => (dates.value.includes(from.value) ? from.value : oldest.value))
const rangeTo = computed(() => (dates.value.includes(to.value) ? to.value : newest.value))

// 两个下拉互相裁剪可选项，天然保证 起始 <= 结束，不需要额外纠正逻辑
const fromOptions = computed(() => dates.value.filter((d) => d <= rangeTo.value))
const toOptions = computed(() => dates.value.filter((d) => d >= rangeFrom.value))
const isFullRange = computed(() => rangeFrom.value === oldest.value && rangeTo.value === newest.value)

const filteredNews = computed(() => {
  let list = newsItems.value.filter((it) => {
    const d = (it.published_at || '').slice(0, 10)
    return d >= rangeFrom.value && d <= rangeTo.value
  })
  if (q.value) {
    const kw = q.value.toLowerCase()
    list = list.filter((it) =>
      `${it.title} ${it.game_name || ''} ${it.summary || ''}`.toLowerCase().includes(kw),
    )
  }
  return list
})

// 只在区间收窄到单日时统计当日新闻数最多的 3 个游戏
const topGames = computed(() => {
  if (rangeFrom.value !== rangeTo.value) return []
  const m = new Map()
  for (const it of filteredNews.value) {
    if (it.game_name) m.set(it.game_name, (m.get(it.game_name) || 0) + 1)
  }
  return [...m.entries()].sort((a, b) => b[1] - a[1]).slice(0, 3)
})

function resetRange() {
  from.value = ''
  to.value = ''
}

/* ---- 每日总结 ---- */
const digestItems = computed(() => src.value?.digest?.items || [])
const currentDigest = computed(
  () => digestItems.value.find((e) => e.date === digestDate.value) || digestItems.value[0] || null,
)

// Top N 单游戏总结由 scripts/summarize_news.py 调 LLM 生成，写在 game_digests[].summary，
// summary_source 标注 llm / rules。早期数据只有 top_games（名字 + 条数、无总结），
// 这里不静默降级成"光秃秃一排名字"，而是显式提示该来源的 digest 需要重跑。
const digestGames = computed(() => {
  const e = currentDigest.value
  if (!e) return []
  if (e.game_digests?.length) return e.game_digests
  return (e.top_games || []).map((g) => ({ ...g, summary: '', summary_source: '' }))
})

const isLegacyDigest = computed(
  () => !!currentDigest.value && !currentDigest.value.game_digests && !!currentDigest.value.top_games,
)

const llmCount = computed(() => digestGames.value.filter((g) => g.summary_source === 'llm').length)

/* ---- 评测 ---- */
const reviewItems = computed(() => src.value?.reviews?.items || [])

function scoreColor(s) {
  const v = Number(s)
  if (!s || Number.isNaN(v)) return 'var(--text-3)'
  if (v >= 9) return 'var(--ok)'
  if (v >= 8) return 'var(--brand)'
  if (v >= 7) return 'var(--warn)'
  return 'var(--danger)'
}

/* ---- 格式化 ---- */
function md(s) {
  return (s || '').slice(5, 10)
}

function stamp(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const p = (n) => String(n).padStart(2, '0')
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

// 搜索命中高亮。正则元字符要转义，否则输入 ( 之类会抛异常。
function highlight(text) {
  const t = String(text ?? '')
  if (!q.value) return [{ t, hit: false }]
  const re = new RegExp(`(${q.value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi')
  return t.split(re).filter(Boolean).map((part) => ({
    t: part,
    hit: part.toLowerCase() === q.value.toLowerCase(),
  }))
}
</script>

<template>
  <div ref="rootRef">
    <div ref="stackRef" class="tab-stack" :class="{ compact }">
      <div class="tab-row">
        <span class="tab-row-label">来源</span>
        <div class="seg">
          <button
            v-for="s in sources"
            :key="s.key"
            :class="{ active: src && src.key === s.key }"
            @click="selectSource(s.key)"
          >{{ s.label }}</button>
        </div>
      </div>

      <span class="tab-sep"></span>
      <div class="tab-row">
        <span class="tab-row-label">分类</span>
        <div class="seg sm">
          <button
            v-for="[key, label] in TABS"
            :key="key"
            :class="{ active: activeTab === key }"
            @click="tab = key"
          >{{ label }}</button>
        </div>
      </div>

      <span class="tab-sep"></span>
      <div class="tab-row">
        <span class="tab-row-label">筛选</span>

        <template v-if="activeTab === 'news' && dates.length">
          <span class="range-wrap">
            <select v-model="from">
              <option v-for="d in fromOptions" :key="d" :value="d">
                {{ md(d) }}（{{ dateCounts.get(d) }}）
              </option>
            </select>
            <span class="sep">至</span>
            <select v-model="to">
              <option v-for="d in toOptions" :key="d" :value="d">
                {{ md(d) }}（{{ dateCounts.get(d) }}）
              </option>
            </select>
            <button v-if="!isFullRange" class="icon-btn" @click="resetRange">全部日期</button>
          </span>
          <span class="search-wrap">
            <input v-model.trim="q" type="search" :placeholder="`在 ${src.label} 新闻中搜索`" />
            <span class="stamp">
              共 {{ filteredNews.length }} 条 · 近 {{ src.news.window_days }} 天 · 更新于 {{ stamp(src.news.crawled_at) }}
            </span>
          </span>
        </template>

        <template v-else-if="activeTab === 'digest' && digestItems.length">
          <select v-model="digestDate">
            <option v-for="e in digestItems" :key="e.date" :value="e.date">
              {{ md(e.date) }}（{{ e.article_count }}）
            </option>
          </select>
          <span v-if="currentDigest" class="stamp">
            {{ currentDigest.article_count }} 条 · {{ currentDigest.game_count }} 款游戏 ·
            更新于 {{ stamp(src.digest.generated_at) }}
          </span>
        </template>

        <template v-else-if="activeTab === 'reviews' && reviewItems.length">
          <span class="stamp">
            共 {{ reviewItems.length }} 条 · 近 {{ src.reviews.window_days }} 天 ·
            更新于 {{ stamp(src.reviews.crawled_at) }}
          </span>
        </template>
      </div>
    </div>

    <!-- ---- 新闻 ---- -->
    <template v-if="activeTab === 'news'">
      <p v-if="src.newsError" class="state err"><span class="em">!</span>{{ src.newsError }}</p>
      <template v-else>
        <p v-if="src.note" class="hint">{{ src.note }}</p>
        <p v-if="topGames.length" class="hint">
          当日热点：
          <span v-for="[n, c] in topGames" :key="n" class="badge brand" style="margin-right: 4px">{{ n }} {{ c }}</span>
        </p>
        <p v-if="!filteredNews.length" class="state">
          <span class="em">—</span>{{ q ? '没有匹配的新闻' : `近 ${src.news?.window_days || 0} 天暂无新闻` }}
        </p>
        <ul v-else class="news-list">
          <li v-for="(it, i) in filteredNews" :key="it.url || i" class="news-item">
            <span class="news-date">{{ md(it.published_at) }}</span>
            <div class="news-main">
              <component :is="it.url ? 'a' : 'span'" class="news-title" :href="it.url || null" target="_blank" rel="noopener"
                ><span v-if="it.game_name" class="news-game">{{ it.game_name }}</span
                ><template v-for="(p, pi) in highlight(it.title)" :key="pi"
                  ><mark v-if="p.hit">{{ p.t }}</mark><template v-else>{{ p.t }}</template
                ></template
              ></component>
              <p v-if="it.summary" class="news-sum">
                <template v-for="(p, pi) in highlight(it.summary)" :key="pi"
                  ><mark v-if="p.hit">{{ p.t }}</mark><template v-else>{{ p.t }}</template
                ></template>
              </p>
            </div>
          </li>
        </ul>
      </template>
    </template>

    <!-- ---- 每日总结 ---- -->
    <template v-else-if="activeTab === 'digest'">
      <p v-if="src.digestError" class="state err"><span class="em">!</span>{{ src.digestError }}</p>
      <p v-else-if="!currentDigest" class="state"><span class="em">—</span>暂无总结</p>
      <template v-else>
        <p class="digest-body">{{ currentDigest.digest }}</p>
        <p v-if="currentDigest.digest_source" class="formula">
          综述来源：{{ currentDigest.digest_source === 'llm' ? 'LLM 生成' : '规则拼接（模型未启用或调用失败）' }}
        </p>

        <div class="card-head">
          <h2>各游戏当日动态（Top {{ src.digest.top_n || 15 }}）</h2>
          <span v-if="llmCount" class="badge brand">{{ llmCount }} / {{ digestGames.length }} 条为 LLM 总结</span>
        </div>

        <p v-if="isLegacyDigest" class="state err">
          <span class="em">!</span>
          {{ src.label }} 的 digest 仍是旧结构（只有 top_games，没有 game_digests），单游戏总结缺失。
          需重跑 scripts/summarize_news.py 生成。
        </p>

        <ol v-if="digestGames.length" class="rank-list">
          <li v-for="(g, i) in digestGames" :key="g.name" class="rank-row">
            <div class="rank-top">
              <span class="rank-no">{{ i + 1 }}</span>
              <span class="rank-name">{{ g.name }}</span>
              <span class="spacer" style="flex: 1"></span>
              <span
                v-if="g.summary_source"
                class="badge"
                :class="{ brand: g.summary_source === 'llm' }"
              >{{ g.summary_source === 'llm' ? 'LLM 总结' : '规则兜底' }}</span>
              <span class="heat-val">{{ g.count }} 条</span>
            </div>
            <p class="rank-meta text">{{ g.summary || '该日无单游戏总结' }}</p>
          </li>
        </ol>
        <p v-else class="state"><span class="em">—</span>当日没有指向具体游戏的新闻</p>
      </template>
    </template>

    <!-- ---- 评测 ---- -->
    <template v-else>
      <p v-if="src.reviewsError" class="state err"><span class="em">!</span>{{ src.reviewsError }}</p>
      <p v-else-if="!reviewItems.length" class="state">
        <span class="em">—</span>近 {{ src.reviews?.window_days || 0 }} 天暂无{{ src.reviewLabel }}
      </p>
      <ul v-else class="news-list">
        <li v-for="(it, i) in reviewItems" :key="it.url || i" class="news-item">
          <span class="news-date score" :style="{ color: scoreColor(it.score) }">{{ it.score || '—' }}</span>
          <div class="news-main">
            <a v-if="it.url" class="news-title" :href="it.url" target="_blank" rel="noopener">{{ it.title }}</a>
            <span v-else class="news-title">{{ it.title }}</span>
            <div class="news-tags">
              <span class="badge">{{ (it.published_at || '').slice(0, 16) }}</span>
              <span v-if="it.author" class="badge">by {{ it.author }}</span>
              <span v-if="it.comment_count !== null && it.comment_count !== undefined" class="badge">
                评论 {{ it.comment_count }}
              </span>
              <span v-for="p in (it.platforms || [])" :key="p" class="badge brand">{{ p }}</span>
            </div>
          </div>
        </li>
      </ul>
    </template>
  </div>
</template>

<style scoped>
/* 评分占位比日期宽一点，字号也大一档，让色阶成为列表的视觉锚点 */
.news-date.score {
  width: 46px;
  font-size: 15px;
  font-weight: 700;
}
</style>

