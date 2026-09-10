<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  data: { type: Object, default: null },
  error: { type: String, default: '' },
})

const hovered = ref(-1)
const range = ref('all')
const sources = computed(() => props.data?.sources || [])
const allDays = computed(() => props.data?.days || [])
const RANGE_OPTIONS = [
  ['week', '近一周', 7],
  ['half-month', '近半月', 15],
  ['month', '近一月', 30],
  ['half-year', '近半年', 180],
  ['all', '总数据', 0],
]
const days = computed(() => {
  const option = RANGE_OPTIONS.find(([key]) => key === range.value)
  const limit = option?.[2] || 0
  if (!limit || !allDays.value.length) return allDays.value
  // 以 UTC 日期计算，避免浏览器本地时区让零点日期向前偏移一天。
  const latest = Date.parse(`${allDays.value[allDays.value.length - 1].date}T00:00:00Z`)
  const start = new Date(latest - (limit - 1) * 86_400_000).toISOString().slice(0, 10)
  return allDays.value.filter((day) => day.date >= start)
})
const colors = ['#4f7cff', '#20a779', '#f59e0b', '#a855f7', '#ef5b5b']
function countFor(day, source) {
  const value = day?.counts?.[source.key]
  return Number.isFinite(value) ? value : null
}
const maxCount = computed(() => Math.max(1, ...days.value.flatMap((day) => sources.value.map((source) => countFor(day, source)).filter((value) => value !== null))))
const plot = { left: 42, top: 16, width: 718, height: 226 }
const x = (index) => plot.left + (days.value.length <= 1 ? plot.width / 2 : index * plot.width / (days.value.length - 1))
const y = (value) => plot.top + plot.height - value / maxCount.value * plot.height
const ticks = computed(() => [...new Set([0, Math.ceil(maxCount.value / 2), maxCount.value])])
const tooltip = computed(() => days.value[hovered.value] || null)

function line(source) {
  const pathFor = (points) => {
    if (points.length < 3) return points.map(([px, py], index) => `${index ? 'L' : 'M'} ${px} ${py}`).join(' ')
    let path = `M ${points[0][0]} ${points[0][1]}`
    for (let index = 0; index < points.length - 1; index++) {
      const before = points[index - 1] || points[index]
      const current = points[index]
      const next = points[index + 1]
      const after = points[index + 2] || next
      path += ` C ${current[0] + (next[0] - before[0]) / 6} ${current[1] + (next[1] - before[1]) / 6}, ${next[0] - (after[0] - current[0]) / 6} ${next[1] - (after[1] - current[1]) / 6}, ${next[0]} ${next[1]}`
    }
    return path
  }
  const segments = []
  let points = []
  days.value.forEach((day, index) => {
    const value = countFor(day, source)
    if (value === null) {
      if (points.length) segments.push(pathFor(points))
      points = []
    } else {
      points.push([x(index), y(value)])
    }
  })
  if (points.length) segments.push(pathFor(points))
  return segments.join(' ')
}
function label(date) { return date?.slice(5).replace('-', '/') || '' }
function hover(event) {
  if (!days.value.length) return
  const box = event.currentTarget.getBoundingClientRect()
  const ratio = Math.max(0, Math.min(1, (event.clientX - box.left) / box.width))
  hovered.value = Math.round(ratio * (days.value.length - 1))
}
</script>

<template>
  <section id="news-daily-trend" class="trend-panel">
    <div class="card-head sticky-heading">
      <h2>各网站每日游戏资讯新增</h2>
      <span class="stamp">{{ data?.temporary ? '当前滚动窗口临时汇总，等待历史快照加载' : `自 ${data?.start_date || '2026-09-01'} 起，每日采集后更新` }}</span>
    </div>
    <p v-if="error" class="state err"><span class="em">!</span>{{ error }}</p>
    <p v-else-if="!days.length" class="state"><span class="em">—</span>暂无每日资讯统计数据</p>
    <template v-else>
      <div class="legend" aria-label="曲线图图例">
        <span v-for="(source, index) in sources" :key="source.key"><i :style="{ background: colors[index % colors.length] }"></i>{{ source.label }}</span>
        <span class="legend-spacer"></span>
        <div class="range-filter" aria-label="曲线图日期范围">
          <button v-for="[key, label] in RANGE_OPTIONS" :key="key" :class="{ active: range === key }" @click="range = key">{{ label }}</button>
        </div>
      </div>
      <div class="chart-wrap">
        <svg class="trend-chart" viewBox="0 0 780 286" role="img" aria-label="各网站每日新增游戏资讯条数曲线图" @mousemove="hover" @mouseleave="hovered = -1">
          <g v-for="tick in ticks" :key="tick">
            <line class="grid" :x1="plot.left" :x2="plot.left + plot.width" :y1="y(tick)" :y2="y(tick)" />
            <text class="axis-text" :x="plot.left - 8" :y="y(tick) + 4" text-anchor="end">{{ tick }}</text>
          </g>
          <path v-for="(source, index) in sources" :key="source.key" class="series" :d="line(source)" :stroke="colors[index % colors.length]" />
          <template v-for="(day, index) in days" :key="day.date">
            <line v-if="index === hovered" class="hover-line" :x1="x(index)" :x2="x(index)" :y1="plot.top" :y2="plot.top + plot.height" />
            <template v-for="(source, sourceIndex) in sources" :key="source.key">
              <circle v-if="countFor(day, source) !== null" :cx="x(index)" :cy="y(countFor(day, source))" r="3" :fill="colors[sourceIndex % colors.length]" />
            </template>
            <text v-if="days.length <= 12 || index % Math.ceil(days.length / 8) === 0 || index === days.length - 1" class="axis-text" :x="x(index)" y="270" text-anchor="middle">{{ label(day.date) }}</text>
          </template>
        </svg>
        <div v-if="tooltip" class="chart-tip">
          <strong>{{ tooltip.date }}</strong>
          <span v-for="source in sources" :key="source.key">{{ source.label }} {{ countFor(tooltip, source) === null ? '暂无数据' : `${countFor(tooltip, source)} 条` }}</span>
        </div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.trend-panel { margin-top: 22px; padding-top: 20px; border-top: 1px solid var(--border); scroll-margin-top: calc(var(--app-bar-h) + 16px); }
.legend { display: flex; flex-wrap: wrap; align-items: center; gap: 10px 18px; margin: 0 0 8px; color: var(--text-2); font-size: 12px; }
.legend span { display: inline-flex; align-items: center; gap: 6px; }.legend i { width: 10px; height: 10px; border-radius: 50%; }
.legend-spacer { flex: 1; }.range-filter { display: inline-flex; flex-wrap: wrap; gap: 3px; padding: 2px; border: 1px solid var(--border); border-radius: var(--r-sm); background: var(--surface); }.range-filter button { border: 0; border-radius: 4px; background: transparent; color: var(--text-2); cursor: pointer; padding: 4px 7px; font: 12px var(--font); }.range-filter button:hover, .range-filter button.active { background: var(--brand-weak); color: var(--brand); }.range-filter button.active { font-weight: 600; }
.chart-wrap { position: relative; }.trend-chart { display: block; width: 100%; overflow: visible; }
.grid { stroke: var(--border); stroke-dasharray: 3 4; }.series { fill: none; stroke-width: 2.5; stroke-linecap: round; stroke-linejoin: round; }.hover-line { stroke: var(--text-3); stroke-dasharray: 3 3; }
.axis-text { fill: var(--text-3); font: 11px var(--font); }.chart-tip { position: absolute; right: 10px; top: 8px; display: grid; gap: 2px; min-width: 136px; padding: 8px 10px; border: 1px solid var(--border); border-radius: var(--r-sm); background: var(--surface-glass); color: var(--text-2); font-size: 12px; box-shadow: var(--shadow-1); pointer-events: none; }.chart-tip strong { color: var(--text); }
@media (max-width: 640px) { .legend-spacer { display: none; }.range-filter { width: 100%; }.range-filter button { flex: 1; padding-inline: 4px; } }
</style>
