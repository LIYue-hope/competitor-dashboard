<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  data: { type: Object, default: null },
  error: { type: String, default: '' },
})

const heatPageSize = ref(20)
const newsPageSize = ref(20)
const heatPage = ref(1)
const newsPage = ref(1)
// 两个榜单按自身指标独立展示，避免要求同一游戏同时具备热度和资讯才可入榜。
const allHeatRows = computed(() => (props.data?.heat_ranking || []).filter((row) => Number(row.heat_score) > 0))
const heatWeeks = computed(() => [...new Set(allHeatRows.value.map((row) => row.week_start).filter(Boolean))].sort())
const latestWeek = computed(() => heatWeeks.value.at(-1) || '')
const previousWeek = computed(() => heatWeeks.value.at(-2) || '')
const heatRows = computed(() => allHeatRows.value.filter((row) => row.week_start === latestWeek.value).sort((a, b) => Number(a.rank) - Number(b.rank)))
const previousRows = computed(() => allHeatRows.value.filter((row) => row.week_start === previousWeek.value))
const previousByName = computed(() => new Map(previousRows.value.map((row) => [row.name, row])))
const consecutiveAppearances = computed(() => {
  const rowsByWeek = new Map(heatWeeks.value.map((week) => [
    week,
    new Set(allHeatRows.value.filter((row) => row.week_start === week).map((row) => row.name)),
  ]))
  const map = new Map()
  for (const row of heatRows.value) {
    let count = 0
    // 从最新周向前逐周检查；任意一周未上榜便终止，不能把历史总次数误称为连续周数。
    for (const week of [...heatWeeks.value].reverse()) {
      if (!rowsByWeek.get(week)?.has(row.name)) break
      count += 1
    }
    map.set(row.name, count)
  }
  return map
})
function movement(row) {
  const previous = previousByName.value.get(row.name)
  if (!previous) return { label: '新上榜', className: 'new', heat: null }
  const rankDelta = Number(previous.rank) - Number(row.rank)
  const heatDelta = Number(row.heat_score) - Number(previous.heat_score)
  return { label: rankDelta > 0 ? `↑ ${rankDelta}` : rankDelta < 0 ? `↓ ${Math.abs(rankDelta)}` : '—', className: rankDelta > 0 ? 'up' : rankDelta < 0 ? 'down' : '', heat: heatDelta }
}
const newsRows = computed(() => (props.data?.news_ranking || []).filter((row) => Number(row.media_count) > 0))

watch(heatPageSize, () => { heatPage.value = 1 })
watch(newsPageSize, () => { newsPage.value = 1 })

function pageRows(rows, page, pageSize) {
  const start = (page.value - 1) * pageSize.value
  return rows.slice(start, start + pageSize.value)
}

const heatShown = computed(() => pageRows(heatRows.value, heatPage, heatPageSize))
const newsShown = computed(() => pageRows(newsRows.value, newsPage, newsPageSize))

function pages(rows, pageSize) { return Math.max(1, Math.ceil(rows.length / pageSize.value)) }

// 与游戏资讯的新闻分页保持一致：页数多时只保留首末页和当前页附近页码。
const newsPageOptions = computed(() => {
  const total = pages(newsRows.value, newsPageSize)
  const current = newsPage.value
  const visible = new Set([1, total, current - 2, current - 1, current, current + 1, current + 2])
  const ordered = [...visible].filter((page) => page >= 1 && page <= total).sort((a, b) => a - b)
  return ordered.reduce((options, page, index) => {
    if (index && page - ordered[index - 1] > 1) options.push(null)
    options.push(page)
    return options
  }, [])
})
function periods(row) {
  const ranges = row.periods?.length ? row.periods : [row]
  const labels = ranges.map((range) => {
    const start = (range.week_start || '').slice(5)
    const end = (range.week_end || '').slice(5)
    return start && end ? `${start} ~ ${end}` : ''
  }).filter(Boolean)
  return labels.length ? labels : ['—']
}
function articleRange(row) {
  const first = (row.first_article_date || '').slice(5)
  const last = (row.last_article_date || '').slice(5)
  return first && last ? `${first} ~ ${last}` : '—'
}
</script>

<template>
  <div class="history-data">
    <p v-if="error" class="state err"><span class="em">!</span>{{ error }}</p>
    <p v-else-if="!data" class="state"><span class="em">—</span>暂无历史数据</p>
    <template v-else>
      <div class="history-note-row">
        <p class="hint">历史数据自 08-31 起累计：热度榜展示最新一周，并与前一周比较排名和热度；游戏资讯榜每日更新。</p>
      </div>

      <section id="history-heat-ranking" class="history-section history-heat-section">
        <div class="card-head sticky-heading">
          <h2>历史热度榜</h2>
          <span class="badge brand">{{ heatRows.length }} / 100 款</span>
          <span class="stamp">{{ latestWeek ? `${latestWeek.slice(5)} 当周 · 对比前一周` : '按游戏热度排序' }}</span>
          <span class="spacer"></span>
          <label class="history-toolbar">
            <span class="stamp">每页显示</span>
            <select v-model.number="heatPageSize" aria-label="历史热度榜每页显示条数">
              <option :value="20">20 条</option>
              <option :value="50">50 条</option>
              <option :value="100">100 条</option>
            </select>
          </label>
        </div>
        <ol v-if="heatShown.length" class="rank-list">
          <li v-for="(row, index) in heatShown" :key="`${row.week_start}-${row.name}`" class="rank-row" :class="{ top: (heatPage - 1) * heatPageSize + index < 3 }">
            <div class="rank-top">
              <span class="rank-no">{{ (heatPage - 1) * heatPageSize + index + 1 }}</span>
              <span class="rank-name">{{ row.name }}</span>
              <span class="history-value"><span>{{ periods(row).join('、') }}</span><strong>热度 {{ row.heat_score }}</strong></span>
            </div>
            <div class="heat-change"><span :class="['movement', movement(row).className]">排名 {{ movement(row).label }}</span><span v-if="movement(row).heat !== null">热度 {{ movement(row).heat > 0 ? '+' : '' }}{{ movement(row).heat.toFixed(1) }}</span><span>连续上榜 {{ consecutiveAppearances.get(row.name) || 1 }} 周</span></div>
          </li>
        </ol>
        <p v-else class="state"><span class="em">—</span>暂无历史热度榜数据</p>
        <div v-if="heatRows.length > heatPageSize" class="pager">
          <button class="icon-btn" :disabled="heatPage === 1" @click="heatPage--">上一页</button>
          <span class="stamp">第 {{ heatPage }} / {{ pages(heatRows, heatPageSize) }} 页</span>
          <button class="icon-btn" :disabled="heatPage === pages(heatRows, heatPageSize)" @click="heatPage++">下一页</button>
        </div>
      </section>

      <section id="history-news-ranking" class="history-section history-news-section">
        <div class="card-head sticky-heading">
          <h2>历史游戏资讯榜</h2>
          <span class="badge brand">{{ newsRows.length }} / 100 款</span>
          <span class="stamp">按历史资讯数量排序</span>
          <span class="spacer"></span>
          <label class="history-toolbar">
            <span class="stamp">每页显示</span>
            <select v-model.number="newsPageSize" aria-label="历史游戏资讯榜每页显示条数">
              <option :value="20">20 条</option>
              <option :value="50">50 条</option>
              <option :value="100">100 条</option>
            </select>
          </label>
        </div>
        <ol v-if="newsShown.length" class="rank-list">
          <li v-for="(row, index) in newsShown" :key="`${row.name}-${articleRange(row)}`" class="rank-row" :class="{ top: (newsPage - 1) * newsPageSize + index < 3 }">
            <div class="rank-top">
              <span class="rank-no">{{ (newsPage - 1) * newsPageSize + index + 1 }}</span>
              <span class="rank-name">{{ row.name }}</span>
              <span class="history-value"><span>{{ articleRange(row) }}</span><strong>累计资讯 {{ row.media_count }} 条</strong></span>
            </div>
          </li>
        </ol>
        <p v-else class="state"><span class="em">—</span>暂无历史游戏资讯榜数据</p>
        <nav v-if="newsRows.length > newsPageSize" class="news-pager" aria-label="历史游戏资讯榜分页">
          <button class="icon-btn" :disabled="newsPage === 1" @click="newsPage--">上一页</button>
          <template v-for="(page, index) in newsPageOptions" :key="page || `gap-${index}`">
            <span v-if="page === null" class="pager-gap" aria-hidden="true">…</span>
            <button
              v-else
              class="icon-btn pager-page"
              :class="{ active: page === newsPage }"
              :aria-current="page === newsPage ? 'page' : null"
              :aria-label="`第 ${page} 页`"
              @click="newsPage = page"
            >{{ page }}</button>
          </template>
          <button class="icon-btn" :disabled="newsPage === pages(newsRows, newsPageSize)" @click="newsPage++">下一页</button>
        </nav>
      </section>
    </template>
  </div>
</template>

<style scoped>
.history-note-row { margin: 0 0 12px; }
.history-note-row .hint { margin: 0; }
.history-toolbar { display: inline-flex; flex: none; align-items: center; gap: 8px; }
select { border: 1px solid var(--border); background: var(--surface); color: var(--text); border-radius: var(--r-sm); padding: 5px 8px; font: 12px var(--font); }
.history-section { --card-padding: 14px; border: 1px solid var(--border); border-radius: var(--r-md); padding: var(--card-padding); margin-top: 14px; background: var(--surface); }
.history-section .card-head { margin-bottom: 10px; }
.pager { display: flex; justify-content: flex-end; align-items: center; gap: 10px; margin-top: 12px; }
.pager .icon-btn { height: 28px; font-size: 12px; }
.news-pager { display: flex; justify-content: flex-end; align-items: center; gap: 6px; margin-top: 12px; flex-wrap: wrap; }
.news-pager .icon-btn { height: 28px; padding: 0 9px; font-size: 12px; }
.news-pager .pager-page { min-width: 28px; justify-content: center; padding: 0 6px; }
.news-pager .pager-page.active { border-color: var(--brand); background: var(--brand-weak); color: var(--brand); }
.pager-gap { color: var(--text-3); line-height: 28px; }
.history-section .rank-list { gap: 5px; }
.history-section .rank-row { --focus-scale: 1.02; }
.history-section .rank-row { padding: 8px 10px; }
.history-section .rank-top { gap: 7px; }
.history-value { display: grid; grid-template-columns: 118px 84px; align-items: center; margin-left: auto; color: var(--text); font-size: 12px; font-variant-numeric: tabular-nums; text-align: right; }
.history-value > span { white-space: nowrap; }
.history-value strong { color: var(--text); font-weight: 700; white-space: nowrap; text-align: right; }
.history-heat-section .history-value { grid-template-columns: 118px 64px; }
.heat-change { display: flex; flex-wrap: wrap; gap: 8px 14px; margin: 5px 0 0 30px; color: var(--text-3); font-size: 12px; }.movement.up { color: var(--ok); font-weight: 650; }.movement.down { color: var(--danger); font-weight: 650; }.movement.new { color: var(--brand); font-weight: 650; }
.history-news-section .history-value { grid-template-columns: 118px 96px; }
@media (max-width: 640px) {
  .history-section .card-head { align-items: flex-start; flex-wrap: wrap; }
  .history-section .card-head .spacer { display: none; }
  .history-toolbar { width: 100%; justify-content: flex-end; }
  .history-value { grid-template-columns: 108px 80px; }
  .history-heat-section .history-value { grid-template-columns: 108px 62px; }
  .history-news-section .history-value { grid-template-columns: 108px 88px; }
}
</style>
