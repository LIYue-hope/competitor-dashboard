<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  data: { type: Object, default: null },
  error: { type: String, default: '' },
})

const hovered = ref(-1)
const chartRef = ref(null)
const sharedQuery = new URLSearchParams(window.location.search)
const range = ref(sharedQuery.get('trendRange') || 'week')
// 总量是所有来源曲线的共同基准，始终显示；占比与均线保持按需开启。
const showShare = ref(sharedQuery.get('trendShare') === '1')
const showAverage = ref(sharedQuery.get('trendAverage') === '1')
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
// 不完整的采集日不能把缺失来源当作 0：那会把“采集失败”画成“没有资讯”。
// 总量与依赖总量的指标以 null 表示未知，SVG 会把它渲染为断线。
const isCompleteDay = (day) => sources.value.length > 0 && sources.value.every((source) => countFor(day, source) !== null)
const totalFor = (day) => isCompleteDay(day)
  ? sources.value.reduce((sum, source) => sum + countFor(day, source), 0)
  : null
// 均线必须从完整历史数据取前 6 天，不能因视图切到「近一周」就把第一天当作 1 日均线。
const averageByDate = computed(() => {
  const result = new Map()
  allDays.value.forEach((day, index) => {
    const window = allDays.value.slice(Math.max(0, index - 6), index + 1)
    const totals = window.map(totalFor)
    result.set(day.date, totals.every((value) => value !== null)
      ? totals.reduce((sum, value) => sum + value, 0) / totals.length
      : null)
  })
  return result
})
const movingAverage = computed(() => days.value.map((day) => averageByDate.value.get(day.date) || 0))
const maxCount = computed(() => {
  const values = days.value.flatMap((day) => sources.value.map((source) => countFor(day, source)).filter((value) => value !== null))
  values.push(...days.value.map(totalFor).filter((value) => value !== null))
  if (showAverage.value) values.push(...movingAverage.value.filter((value) => value !== null))
  return Math.max(1, ...values)
})
const plot = { left: 42, top: 16, width: 718, height: 226 }
const x = (index) => plot.left + (days.value.length <= 1 ? plot.width / 2 : index * plot.width / (days.value.length - 1))
const y = (value) => plot.top + plot.height - value / maxCount.value * plot.height
const ticks = computed(() => [...new Set([0, Math.ceil(maxCount.value / 2), maxCount.value])])
const tooltip = computed(() => days.value[hovered.value] || null)
watch([range, showShare, showAverage], () => {
  const url = new URL(window.location.href)
  url.searchParams.set('trendRange', range.value)
  showShare.value ? url.searchParams.set('trendShare', '1') : url.searchParams.delete('trendShare')
  showAverage.value ? url.searchParams.set('trendAverage', '1') : url.searchParams.delete('trendAverage')
  window.history.replaceState({}, '', url)
})
function segmentedPath(values) {
  const segments = []
  let points = []
  values.forEach((value, index) => {
    if (value === null) {
      if (points.length) segments.push(smoothPath(points))
      points = []
    } else {
      points.push([x(index), y(value)])
    }
  })
  if (points.length) segments.push(smoothPath(points))
  return segments.join(' ')
}
const averagePath = computed(() => segmentedPath(movingAverage.value))
const totalPath = computed(() => segmentedPath(days.value.map(totalFor)))
// 占比不能只藏在 tooltip 里：勾选后直接给出当前范围最新 14 个数据日的 100% 堆叠条。
// 仅完整采集日可以比较占比；缺失来源不能伪装成占比为 0。
const shareDays = computed(() => days.value.slice(-14).map((day) => {
  const total = totalFor(day)
  return {
    date: day.date,
    total,
    complete: total !== null,
    items: total === null ? [] : sources.value.map((source, index) => {
      const count = countFor(day, source)
      return { ...source, count, percent: total ? count / total * 100 : 0, color: colors[index % colors.length] }
    }).filter((item) => item.count > 0),
  }
}))

function smoothPath(points) {
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

function line(source) {
  const segments = []
  let points = []
  days.value.forEach((day, index) => {
    const value = countFor(day, source)
    if (value === null) {
      if (points.length) segments.push(smoothPath(points))
      points = []
    } else {
      points.push([x(index), y(value)])
    }
  })
  if (points.length) segments.push(smoothPath(points))
  return segments.join(' ')
}
function label(date) { return date?.slice(5).replace('-', '/') || '' }
function hover(event) {
  if (!days.value.length) return
  const box = event.currentTarget.getBoundingClientRect()
  const ratio = Math.max(0, Math.min(1, (event.clientX - box.left) / box.width))
  hovered.value = Math.round(ratio * (days.value.length - 1))
}

// 报告场景无需额外依赖：将当前 SVG（含已选的均线状态）序列化并绘制到 canvas，下载 PNG。
function downloadPng() {
  const source = chartRef.value
  if (!source) return
  const svg = source.cloneNode(true)
  svg.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
  svg.insertAdjacentHTML('afterbegin', '<style>.grid{stroke:#d0d5dd;stroke-dasharray:3 4}.series{fill:none;stroke-width:2.5;stroke-linecap:round;stroke-linejoin:round}.total-series{fill:none;stroke:#101828;stroke-width:2.5;stroke-linecap:round;stroke-linejoin:round}.average-series{fill:none;stroke:#101828;stroke-width:2;stroke-dasharray:7 4;stroke-linecap:round}.hover-line{stroke:#98a2b3;stroke-dasharray:3 3}.axis-text{fill:#667085;font:11px sans-serif}</style>')
  const url = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(svg)], { type: 'image/svg+xml;charset=utf-8' }))
  const image = new Image()
  image.onload = () => {
    const canvas = document.createElement('canvas')
    canvas.width = 1560; canvas.height = 572
    const context = canvas.getContext('2d')
    context.fillStyle = '#ffffff'; context.fillRect(0, 0, canvas.width, canvas.height)
    context.drawImage(image, 0, 0, canvas.width, canvas.height)
    URL.revokeObjectURL(url)
    canvas.toBlob((blob) => {
      if (!blob) return
      const link = document.createElement('a')
      link.href = URL.createObjectURL(blob)
      link.download = `游戏资讯趋势-${new Date().toISOString().slice(0, 10)}.png`
      link.click(); URL.revokeObjectURL(link.href)
    }, 'image/png')
  }
  image.onerror = () => URL.revokeObjectURL(url)
  image.src = url
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
        <span><i class="legend-total"></i>总量</span>
        <span v-if="showAverage"><i class="legend-average"></i>7 日移动均线</span>
        <span class="legend-spacer"></span>
        <div class="range-filter" aria-label="曲线图日期范围">
          <button v-for="[key, label] in RANGE_OPTIONS" :key="key" :class="{ active: range === key }" @click="range = key">{{ label }}</button>
        </div>
        <label class="chart-option"><input v-model="showShare" type="checkbox"> 各源占比</label>
        <label class="chart-option"><input v-model="showAverage" type="checkbox"> 7 日移动均线</label>
        <button class="icon-btn chart-export" @click="downloadPng">下载趋势 PNG</button>
      </div>
      <div class="chart-wrap">
        <svg ref="chartRef" class="trend-chart" viewBox="0 0 780 286" role="img" aria-label="各网站每日新增游戏资讯条数曲线图" @mousemove="hover" @mouseleave="hovered = -1">
          <g v-for="tick in ticks" :key="tick">
            <line class="grid" :x1="plot.left" :x2="plot.left + plot.width" :y1="y(tick)" :y2="y(tick)" />
            <text class="axis-text" :x="plot.left - 8" :y="y(tick) + 4" text-anchor="end">{{ tick }}</text>
          </g>
          <path v-for="(source, index) in sources" :key="source.key" class="series" :d="line(source)" :stroke="colors[index % colors.length]" />
          <path class="series total-series" :d="totalPath" />
          <path v-if="showAverage" class="average-series" :d="averagePath" />
          <template v-for="(day, index) in days" :key="day.date">
            <line v-if="index === hovered" class="hover-line" :x1="x(index)" :x2="x(index)" :y1="plot.top" :y2="plot.top + plot.height" />
            <template v-for="(source, sourceIndex) in sources" :key="source.key">
              <circle v-if="countFor(day, source) !== null" :cx="x(index)" :cy="y(countFor(day, source))" r="3" :fill="colors[sourceIndex % colors.length]" />
            </template>
            <circle v-if="totalFor(day) !== null" :cx="x(index)" :cy="y(totalFor(day))" r="3" class="total-dot" />
            <text v-if="days.length <= 12 || index % Math.ceil(days.length / 8) === 0 || index === days.length - 1" class="axis-text" :x="x(index)" y="270" text-anchor="middle">{{ label(day.date) }}</text>
          </template>
        </svg>
        <div v-if="tooltip" class="chart-tip">
          <strong>{{ tooltip.date }}</strong>
          <span v-for="source in sources" :key="source.key">{{ source.label }} {{ countFor(tooltip, source) === null ? '暂无数据' : `${countFor(tooltip, source)} 条` }}</span>
          <span class="tip-total">合计 {{ totalFor(tooltip) === null ? '数据不完整' : `${totalFor(tooltip)} 条` }}</span>
          <template v-if="showShare"><span v-for="source in sources" :key="`${source.key}-share`">{{ source.label }} 占比 {{ totalFor(tooltip) === null ? '数据不完整' : `${(countFor(tooltip, source) / totalFor(tooltip) * 100).toFixed(1)}%` }}</span></template>
          <span v-if="showAverage">7 日均线 {{ movingAverage[hovered] === null || movingAverage[hovered] === undefined ? '数据不完整' : `${movingAverage[hovered].toFixed(1)} 条` }}</span>
        </div>
        <section v-if="showShare" class="source-share" aria-label="各来源每日资讯占比">
          <div class="share-head"><strong>各来源占比</strong><span class="stamp">当前范围最新 {{ shareDays.length }} 个数据日 · 每条为当日 100%</span></div>
          <p v-if="!shareDays.length" class="hint">暂无可计算的来源占比</p>
          <div v-else class="share-list">
            <div v-for="day in shareDays" :key="day.date" class="share-row">
              <span class="share-date">{{ label(day.date) }}</span>
              <div class="share-bar" :class="{ incomplete: !day.complete }" :aria-label="day.complete ? `${day.date} 共 ${day.total} 条` : `${day.date} 数据不完整`">
                <span v-if="!day.complete" class="share-unknown">数据不完整</span>
                <span v-for="item in day.items" :key="item.key" class="share-segment" :style="{ width: `${item.percent}%`, background: item.color }" :title="`${item.label} ${item.count} 条，占 ${item.percent.toFixed(1)}%`"></span>
              </div>
              <span class="share-total">{{ day.complete ? `${day.total} 条` : '未知' }}</span>
            </div>
          </div>
        </section>
      </div>
    </template>
  </section>
</template>

<style scoped>
.trend-panel { margin-top: 22px; padding-top: 20px; border-top: 1px solid var(--border); scroll-margin-top: calc(var(--app-bar-h) + 16px); }
.legend { display: flex; flex-wrap: wrap; align-items: center; gap: 10px 18px; margin: 0 0 8px; color: var(--text-2); font-size: 12px; }
.legend span { display: inline-flex; align-items: center; gap: 6px; }.legend i { width: 10px; height: 10px; border-radius: 50%; }.legend i.legend-total { background: var(--text); }.legend i.legend-average { background: var(--text-3); }
.legend-spacer { flex: 1; }.range-filter { display: inline-flex; flex-wrap: wrap; gap: 3px; padding: 2px; border: 1px solid var(--border); border-radius: var(--r-sm); background: var(--surface); }.range-filter button { border: 0; border-radius: 4px; background: transparent; color: var(--text-2); cursor: var(--cursor-link), pointer; padding: 4px 7px; font: 12px var(--font); }.range-filter button:hover, .range-filter button.active { background: var(--brand-weak); color: var(--brand); }.range-filter button.active { font-weight: 600; }
.chart-wrap { position: relative; }.trend-chart { display: block; width: 100%; overflow: visible; }
.grid { stroke: var(--border); stroke-dasharray: 3 4; }.series { fill: none; stroke-width: 2.5; stroke-linecap: round; stroke-linejoin: round; }.total-series { stroke: var(--text); }.total-dot { fill: var(--text); }.average-series { fill: none; stroke: var(--text-3); stroke-width: 2; stroke-dasharray: 7 4; stroke-linecap: round; }.hover-line { stroke: var(--text-3); stroke-dasharray: 3 3; }
.axis-text { fill: var(--text-3); font: 11px var(--font); }.chart-tip { position: absolute; right: 10px; top: 8px; display: grid; gap: 2px; min-width: 136px; padding: 8px 10px; border: 1px solid var(--border); border-radius: var(--r-sm); background: var(--surface-glass); color: var(--text-2); font-size: 12px; box-shadow: var(--shadow-1); pointer-events: none; }.chart-tip strong { color: var(--text); }
.chart-option { display: inline-flex; align-items: center; gap: 4px; font-size: 12px; color: var(--text-2); cursor: var(--cursor-link), pointer; }.tip-total { margin-top: 3px; color: var(--text); font-weight: 600; }
.chart-export { height: 28px; padding-inline: 9px; font-size: 12px; }
.source-share { margin-top: 14px; padding: 12px; border: 1px solid var(--border); border-radius: var(--r-sm); background: var(--surface-2); }.share-head { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 9px; color: var(--text); font-size: 13px; }.share-list { display: grid; gap: 7px; }.share-row { display: grid; grid-template-columns: 42px minmax(0, 1fr) 48px; align-items: center; gap: 8px; font-size: 12px; }.share-date, .share-total { color: var(--text-2); font-variant-numeric: tabular-nums; }.share-total { text-align: right; }.share-bar { display: flex; min-height: 12px; overflow: hidden; border-radius: 999px; background: var(--border); }.share-segment { min-width: 0; transition: width .15s ease; }.share-bar.incomplete { justify-content: center; background: var(--surface); border: 1px dashed var(--border); }.share-unknown { color: var(--text-3); font-size: 11px; }
@media (max-width: 640px) { .legend-spacer { display: none; }.range-filter { width: 100%; }.range-filter button { flex: 1; padding-inline: 4px; } }
</style>
