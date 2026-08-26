<script setup>
import { ref, computed, watch } from 'vue'
import GameCard from './GameCard.vue'
import { useStickyTabs, jumpToAnchor } from '../composables/useStickyTabs.js'

const props = defineProps({
  taptap: { type: Array, default: () => [] },
  haoyou: { type: Object, default: null },
  jiuyou: { type: Object, default: null },
  p16: { type: Object, default: null },
  errors: { type: Object, default: () => ({}) }, // { taptap, haoyou, jiuyou, p16 }
  active: { type: Boolean, default: false },
})

const SOURCES = [
  ['taptap', 'TapTap'],
  ['haoyou', '好游快爆'],
  ['jiuyou', '九游'],
  ['p16', '游资网'],
]

const tab = ref('taptap')
const q = ref('')

const stackRef = ref(null)
const rootRef = ref(null)
const activeRef = computed(() => props.active)
const { compact, activeAnchor, remeasure } = useStickyTabs(stackRef, rootRef, activeRef)

// 切来源 / 改搜索词都会换掉整段内容，吸顶栏高度和锚点位置随之变化，要重新实测
watch([tab, q], () => remeasure())

const error = computed(() => props.errors[tab.value] || '')

const crawledAt = computed(() =>
  tab.value === 'taptap' ? props.taptap[0]?.crawled_at : props[tab.value]?.crawled_at,
)

/**
 * 日期分组：不重排内容，只是把既有顺序切成带锚点的段落。
 * 好游快爆 / 九游 / 游资网 数据本身就是按天分组的，直接用；
 * TapTap 是扁平列表，按 release_date 归组并保持首次出现顺序（等价于原排序）。
 */
const groups = computed(() => {
  if (tab.value !== 'taptap') {
    return (props[tab.value]?.days || []).map((d) => ({
      date: d.date,
      label: d.date_label || d.date,
      games: d.games || [],
    }))
  }
  const out = []
  for (const g of props.taptap) {
    const date = g.release_date || 'unknown'
    let grp = out.find((x) => x.date === date)
    if (!grp) {
      grp = { date, label: date === 'unknown' ? '日期未知' : `上线 ${date}`, games: [] }
      out.push(grp)
    }
    grp.games.push(g)
  }
  return out
})

function match(g) {
  if (!q.value) return true
  const kw = q.value.toLowerCase()
  return [g.game_name, g.publisher, (g.categories || []).join('')]
    .join(' ')
    .toLowerCase()
    .includes(kw)
}

const shown = computed(() =>
  groups.value
    .map((g) => ({ ...g, games: g.games.filter(match), id: `d-${tab.value}-${g.date}` }))
    .filter((g) => g.games.length),
)

const total = computed(() => shown.value.reduce((n, g) => n + g.games.length, 0))

function stamp(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const p = (n) => String(n).padStart(2, '0')
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}
</script>

<template>
  <div ref="rootRef">
    <div ref="stackRef" class="tab-stack" :class="{ compact }">
      <div class="tab-row">
        <span class="tab-row-label">来源</span>
        <div class="seg">
          <button
            v-for="[key, label] in SOURCES"
            :key="key"
            :class="{ active: tab === key }"
            @click="tab = key"
          >{{ label }}</button>
        </div>
      </div>

      <!-- 日期 Tab 走锚点跳转而不是过滤：内容顺序不变，点了只是滚过去，滚动时高亮跟着走。
           用 .wrap 方角容器：九游有 10 个日期，胶囊圆角一换行就兜不住末尾按钮。 -->
      <template v-if="shown.length">
        <span class="tab-sep"></span>
        <div class="tab-row">
          <span class="tab-row-label">日期</span>
          <div class="seg sm wrap">
            <button
              v-for="g in shown"
              :key="g.id"
              :class="{ active: activeAnchor === g.id }"
              @click="jumpToAnchor(g.id)"
            >{{ g.label }}</button>
          </div>
        </div>
      </template>

      <span class="tab-sep"></span>
      <div class="tab-row">
        <span class="tab-row-label">筛选</span>
        <span class="search-wrap">
          <input v-model.trim="q" type="search" placeholder="搜索游戏名 / 发行商 / 类型" />
          <span class="stamp">{{ total }} 款 · ★ 提及挂机/搬砖玩法</span>
        </span>
      </div>
    </div>

    <p v-if="error" class="state err"><span class="em">!</span>{{ error }}</p>
    <p v-else-if="!shown.length" class="state">
      <span class="em">—</span>{{ q ? `没有匹配「${q}」的游戏` : '暂无数据' }}
    </p>
    <template v-else>
      <template v-for="g in shown" :key="g.id">
        <h3 :id="g.id" class="date-head">
          <span>{{ g.label }}</span>
          <span class="badge">{{ g.games.length }} 款</span>
          <span class="line"></span>
        </h3>
        <div class="grid">
          <GameCard v-for="game in g.games" :key="game.source_url || game.detail_url || game.game_name" :game="game" />
        </div>
      </template>
      <p v-if="crawledAt" class="hint" style="margin-top: 16px">更新于 {{ stamp(crawledAt) }}</p>
    </template>
  </div>
</template>
