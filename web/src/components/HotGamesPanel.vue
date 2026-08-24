<script setup>
import { ref, computed, watch } from 'vue'
import { useStickyTabs } from '../composables/useStickyTabs.js'

const props = defineProps({
  data: { type: Object, default: null },
  // { crawled_at, window_days, publishers: [ {key, label, games: [...]} ] }
  error: { type: String, default: '' },
  active: { type: Boolean, default: false },
})

const stackRef = ref(null)
const rootRef = ref(null)
const activeRef = computed(() => props.active)
const { compact, remeasure } = useStickyTabs(stackRef, rootRef, activeRef)

const pubKey = ref('')
const gameName = ref('')
const type = ref('全部')

const publishers = computed(() => props.data?.publishers || [])

// 三级选中项都容错回退：发行商 → 该发行商第一个游戏 → 全部板块。
// 数据刷新后选中项可能已不存在，回退比白屏好。
const pub = computed(
  () => publishers.value.find((p) => p.key === pubKey.value) || publishers.value[0] || null,
)

const game = computed(() => {
  const games = pub.value?.games || []
  return games.find((g) => g.game_name === gameName.value) || games[0] || null
})

const updates = computed(() => game.value?.updates || [])

// 板块 Tab 只列该游戏实际出现过的类型，避免出现点了就是空的死 Tab
const typeCounts = computed(() => {
  const m = new Map()
  for (const u of updates.value) m.set(u.type, (m.get(u.type) || 0) + 1)
  return m
})

const activeType = computed(() => (typeCounts.value.has(type.value) ? type.value : '全部'))

const list = computed(() =>
  activeType.value === '全部'
    ? updates.value
    : updates.value.filter((u) => u.type === activeType.value),
)

function selectPub(key) {
  pubKey.value = key
  gameName.value = ''
  type.value = '全部'
}

function selectGame(name) {
  gameName.value = name
  type.value = '全部'
}

// 换厂商/游戏/板块都会换掉整段内容，吸顶栏高度随之变化，要重新实测补偿量
watch([pubKey, gameName, type], () => remeasure())

// 动态类型配色，语义与改版前保持一致
function typeClass(t) {
  return {
    版本前瞻: 't-foresight',
    新活动: 't-activity',
    更新公告: 't-update',
    赛事: 't-esports',
    公告: 't-news',
    资讯: 't-news',
    新闻: 't-news',
    安全公告: 't-warning',
    处罚公告: 't-warning',
  }[t] || 't-default'
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
  <div ref="rootRef">
    <p v-if="error" class="state err"><span class="em">!</span>{{ error }}</p>
    <p v-else-if="!publishers.length" class="state"><span class="em">—</span>暂无数据</p>

    <template v-else>
      <div ref="stackRef" class="tab-stack" :class="{ compact }">
        <div class="tab-row">
          <span class="tab-row-label">厂商</span>
          <div class="seg">
            <button
              v-for="p in publishers"
              :key="p.key"
              :class="{ active: pub && pub.key === p.key }"
              @click="selectPub(p.key)"
            >{{ p.label }}（{{ p.games.length }}）</button>
          </div>
        </div>

        <span class="tab-sep"></span>
        <div class="tab-row">
          <span class="tab-row-label">游戏</span>
          <div class="seg sm wrap">
            <button
              v-for="g in (pub ? pub.games : [])"
              :key="g.game_name"
              :class="{ active: game && game.game_name === g.game_name }"
              @click="selectGame(g.game_name)"
            >{{ g.game_name }}（{{ (g.updates || []).length }}）</button>
          </div>
        </div>

        <span class="tab-sep"></span>
        <div class="tab-row">
          <span class="tab-row-label">板块</span>
          <div class="seg sm wrap">
            <button
              class="type-btn t-default"
              :class="{ active: activeType === '全部' }"
              @click="type = '全部'"
            >全部（{{ updates.length }}）</button>
            <button
              v-for="[t, n] in typeCounts"
              :key="t"
              class="type-btn"
              :class="[typeClass(t), { active: activeType === t }]"
              @click="type = t"
            >{{ t }}（{{ n }}）</button>
          </div>
        </div>
      </div>

      <div class="card-head">
        <h2>{{ game ? game.game_name : '' }}</h2>
        <!-- 同一 tab 下多家公司混排时（鹰角/库洛/叠纸）才有 company -->
        <span v-if="game && game.company" class="stamp">（{{ game.company }}）</span>
        <span
          v-if="game && game.has_afk_grinding_tag"
          class="badge star"
          title="相关动态中提及挂机/搬砖玩法"
        >★ 提及挂机/搬砖</span>
        <span class="badge">{{ list.length }} 条</span>
        <span class="spacer"></span>
        <a
          v-if="game && game.official_url"
          class="stamp"
          :href="game.official_url"
          target="_blank"
          rel="noopener"
        >官网 ↗</a>
      </div>

      <p v-if="!game" class="state"><span class="em">—</span>该发行商暂无监测游戏</p>
      <p v-else-if="game.source_status === 'pending'" class="state">
        <span class="em">—</span>官方来源待接入，暂只提供官网直达
      </p>
      <p v-else-if="game.source_status === 'error'" class="state err">
        <span class="em">!</span>本次采集失败，稍后重试
      </p>
      <p v-else-if="!updates.length" class="state">
        <span class="em">—</span>近 {{ data.window_days }} 天暂无官方动态
      </p>
      <ul v-else class="news-list">
        <li v-for="(u, i) in list" :key="u.url || i" class="news-item">
          <span class="news-date">{{ md(u.date) }}</span>
          <div class="news-main">
            <a v-if="u.url" class="news-title" :href="u.url" target="_blank" rel="noopener">{{ u.title }}</a>
            <span v-else class="news-title">{{ u.title }}</span>
            <p v-if="u.summary" class="news-sum">{{ u.summary }}</p>
            <div class="news-tags">
              <span class="type-tag" :class="typeClass(u.type)">{{ u.type }}</span>
            </div>
          </div>
        </li>
      </ul>

      <p class="hint" style="margin-top: 16px">
        近 {{ data.window_days }} 天官方公告 · 更新于 {{ stamp(data.crawled_at) }}
      </p>
    </template>
  </div>
</template>
