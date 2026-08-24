<script setup>
import { computed } from 'vue'

const props = defineProps({
  data: { type: Object, default: null },
  error: { type: String, default: '' },
})

const rows = computed(() => props.data?.hot_ranking || [])

// 热度条按榜首归一化：把"热度 42.3"从纯数字变成可横向比较的长度
const maxHeat = computed(() => Math.max(...rows.value.map((r) => r.heat_score), 1))

const kpis = computed(() => {
  const d = props.data
  if (!d) return []
  return [
    ['统计周期', `${md(d.week_start)} ~ ${md(d.week_end)}`, ''],
    ['资讯总量', d.article_count, '条'],
    ['涉及游戏', d.game_count, '款'],
    ['入榜游戏', rows.value.length, '款'],
  ]
})

const RANK_LIST_LABELS = { hot: '热门榜', reserve: '预约榜', new: '新品榜' }

function rankListsText(lists) {
  return (lists || []).map((k) => RANK_LIST_LABELS[k] || k).join(' / ')
}

// 一行里出现的所有计量口径，缺的项不渲染
function metas(r) {
  return [
    `资讯 ${r.media_count} 条`,
    `${r.source_count} 个来源`,
    r.reservation_label && `预约 ${r.reservation_label}`,
    r.follow_delta_label && `周内新增关注 ${r.follow_delta_label}`,
    r.best_rank && `TapTap 最高第 ${r.best_rank}（${rankListsText(r.rank_lists)}）`,
    r.official_count && `官方动态 ${r.official_count}`,
  ].filter(Boolean)
}

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
</script>

<template>
  <div>
    <p v-if="error" class="state err"><span class="em">!</span>{{ error }}</p>
    <p v-else-if="!data" class="state"><span class="em">—</span>暂无上周总结</p>

    <template v-else>
      <div class="kpi-row">
        <div v-for="[k, v, unit] in kpis" :key="k" class="kpi">
          <div class="k">{{ k }}</div>
          <div class="v">{{ v }}<small v-if="unit">{{ unit }}</small></div>
        </div>
      </div>

      <p class="digest-body">{{ data.digest }}</p>
      <p v-if="data.heat_formula" class="formula">{{ data.heat_formula }}</p>

      <div class="card-head">
        <h2>综合热度榜</h2>
        <span class="spacer"></span>
        <span v-if="data.generated_at" class="stamp">更新于 {{ stamp(data.generated_at) }}</span>
      </div>

      <ol v-if="rows.length" class="rank-list">
        <li
          v-for="r in rows"
          :key="r.rank + r.name"
          class="rank-row"
          :class="{ top: r.rank <= 3 }"
        >
          <div class="rank-top">
            <span class="rank-no">{{ r.rank }}</span>
            <span class="rank-name">{{ r.name }}</span>
            <span class="heat-bar"><i :style="{ width: (r.heat_score / maxHeat * 100).toFixed(1) + '%' }"></i></span>
            <span class="heat-val">{{ r.heat_score }}</span>
          </div>
          <p class="rank-meta">
            <span v-for="m in metas(r)" :key="m">{{ m }}</span>
          </p>
          <ul v-if="r.news && r.news.length" class="rank-news">
            <li v-for="n in r.news" :key="n.url">
              <a :href="n.url" target="_blank" rel="noopener noreferrer">{{ n.title }}</a>
              <span class="src">{{ n.source }} · {{ n.published_at }}</span>
            </li>
          </ul>
        </li>
      </ol>
      <p v-else class="state"><span class="em">—</span>上周暂无达到入榜门槛的游戏</p>
    </template>
  </div>
</template>
