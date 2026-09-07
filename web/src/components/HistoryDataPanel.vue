<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  data: { type: Object, default: null },
  error: { type: String, default: '' },
})

const pageSize = ref(20)
const heatPage = ref(1)
const newsPage = ref(1)
const heatRows = computed(() => props.data?.heat_ranking || [])
const newsRows = computed(() => props.data?.news_ranking || [])

watch(pageSize, () => { heatPage.value = 1; newsPage.value = 1 })

function pageRows(rows, page) {
  const start = (page.value - 1) * pageSize.value
  return rows.slice(start, start + pageSize.value)
}

const heatShown = computed(() => pageRows(heatRows.value, heatPage))
const newsShown = computed(() => pageRows(newsRows.value, newsPage))

function pages(rows) { return Math.max(1, Math.ceil(rows.length / pageSize.value)) }
function period(row) {
  const start = (row.week_start || '').slice(5)
  const end = (row.week_end || '').slice(5)
  return start && end ? `${start} ~ ${end}` : '—'
}
</script>

<template>
  <div class="history-data">
    <p class="hint">历史数据自 08-31 起累计；每周成稿后自动补充。各榜单最多保留前 100 款游戏。</p>
    <p v-if="error" class="state err"><span class="em">!</span>{{ error }}</p>
    <p v-else-if="!data" class="state"><span class="em">—</span>暂无历史数据</p>
    <template v-else>
      <div class="history-toolbar">
        <span class="stamp">每页显示</span>
        <select v-model.number="pageSize" aria-label="每页显示条数">
          <option :value="20">20 条</option>
          <option :value="50">50 条</option>
          <option :value="100">100 条</option>
        </select>
      </div>

      <section class="history-section">
        <div class="card-head">
          <h2>历史热度榜</h2>
          <span class="badge brand">{{ heatRows.length }} / 100 款</span>
          <span class="spacer"></span>
          <span class="stamp">按游戏热度排序</span>
        </div>
        <ol v-if="heatShown.length" class="rank-list">
          <li v-for="(row, index) in heatShown" :key="`${row.week_start}-${row.name}`" class="rank-row" :class="{ top: (heatPage - 1) * pageSize + index < 3 }">
            <div class="rank-top">
              <span class="rank-no">{{ (heatPage - 1) * pageSize + index + 1 }}</span>
              <span class="rank-name">{{ row.name }}</span>
              <span class="heat-bar"><i :style="{ width: `${Math.min(row.heat_score || 0, 100)}%` }"></i></span>
              <span class="heat-val">热度 {{ row.heat_score }}</span>
            </div>
            <p class="rank-meta"><span>上榜周期 <strong>{{ period(row) }}</strong></span><span>资讯 {{ row.media_count }} 条</span><span>{{ row.source_count }} 个来源</span></p>
          </li>
        </ol>
        <p v-else class="state"><span class="em">—</span>暂无历史热度榜数据</p>
        <div v-if="heatRows.length > pageSize" class="pager">
          <button class="icon-btn" :disabled="heatPage === 1" @click="heatPage--">上一页</button>
          <span class="stamp">第 {{ heatPage }} / {{ pages(heatRows) }} 页</span>
          <button class="icon-btn" :disabled="heatPage === pages(heatRows)" @click="heatPage++">下一页</button>
        </div>
      </section>

      <section class="history-section">
        <div class="card-head">
          <h2>历史游戏资讯榜</h2>
          <span class="badge brand">{{ newsRows.length }} / 100 款</span>
          <span class="spacer"></span>
          <span class="stamp">按历史资讯数量排序</span>
        </div>
        <ol v-if="newsShown.length" class="rank-list">
          <li v-for="(row, index) in newsShown" :key="`${row.week_start}-${row.name}`" class="rank-row" :class="{ top: (newsPage - 1) * pageSize + index < 3 }">
            <div class="rank-top">
              <span class="rank-no">{{ (newsPage - 1) * pageSize + index + 1 }}</span>
              <span class="rank-name">{{ row.name }}</span>
              <span class="heat-bar"><i :style="{ width: `${Math.min((row.media_count / (newsRows[0]?.media_count || 1)) * 100, 100)}%` }"></i></span>
              <span class="heat-val">资讯 {{ row.media_count }} 条</span>
            </div>
            <p class="rank-meta"><span>上榜周期 <strong>{{ period(row) }}</strong></span><span>热度 {{ row.heat_score }}</span><span>{{ row.source_count }} 个来源</span></p>
          </li>
        </ol>
        <p v-else class="state"><span class="em">—</span>暂无历史游戏资讯榜数据</p>
        <div v-if="newsRows.length > pageSize" class="pager">
          <button class="icon-btn" :disabled="newsPage === 1" @click="newsPage--">上一页</button>
          <span class="stamp">第 {{ newsPage }} / {{ pages(newsRows) }} 页</span>
          <button class="icon-btn" :disabled="newsPage === pages(newsRows)" @click="newsPage++">下一页</button>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.history-toolbar { display: flex; justify-content: flex-end; align-items: center; gap: 8px; margin: 0 0 12px; }
select { border: 1px solid var(--border); background: var(--surface); color: var(--text); border-radius: var(--r-sm); padding: 5px 8px; font: 12px var(--font); }
.history-section { border: 1px solid var(--border); border-radius: var(--r-md); padding: 14px; margin-top: 14px; background: var(--surface); }
.history-section .card-head { margin-bottom: 10px; }
.pager { display: flex; justify-content: flex-end; align-items: center; gap: 10px; margin-top: 12px; }
.pager .icon-btn { height: 28px; font-size: 12px; }
</style>
