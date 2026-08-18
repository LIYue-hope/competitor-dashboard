<script setup>
import { ref, computed, reactive } from 'vue'

const props = defineProps({
  data: {
    type: Object,
    required: true,
    // { crawled_at, window_days, publishers: [ {key, label, games: [...] } ] }
  },
})

const publishers = computed(() => props.data.publishers || [])

// 当前激活的发行商 Tab，默认选中第一个（腾讯）。
const activePublisher = ref(publishers.value[0]?.key || '')

const activeGroup = computed(
  () => publishers.value.find((p) => p.key === activePublisher.value) || null
)

function selectPublisher(key) {
  activePublisher.value = key
}

// 每张游戏卡片内部按动态类型（全部/版本前瞻/更新公告/新活动/公告）切换小 Tab，
// 各卡片互相独立，用 game_name 做 key 记录当前选中的类型。
const activeTypeByGame = reactive({})

function typesOf(game) {
  const set = new Set(game.updates.map((u) => u.type))
  return ['全部', ...set]
}

function activeType(game) {
  return activeTypeByGame[game.game_name] || '全部'
}

function selectType(game, type) {
  activeTypeByGame[game.game_name] = type
}

function filteredUpdates(game) {
  const type = activeType(game)
  if (type === '全部') return game.updates
  return game.updates.filter((u) => u.type === type)
}

function formatCrawledAt(isoString) {
  if (!isoString) return ''
  const d = new Date(isoString)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

// 不同动态类型给不同颜色标记，便于快速区分。
function typeClass(type) {
  switch (type) {
    case '版本前瞻':
      return 'type-foresight'
    case '新活动':
      return 'type-activity'
    case '更新公告':
      return 'type-update'
    case '赛事':
      return 'type-esports'
    // 公告/资讯/新闻同属中性信息类，复用一套配色
    case '公告':
    case '资讯':
    case '新闻':
      return 'type-news'
    // 安全公告/处罚公告属警示类
    case '安全公告':
    case '处罚公告':
      return 'type-warning'
    default:
      return 'type-default'
  }
}
</script>

<template>
  <div class="hot-panel">
    <div v-if="data.crawled_at" class="panel-meta">
      <div class="source-line">
        热门游戏动态：近 {{ data.window_days }} 天官方公告 · 更新于 {{ formatCrawledAt(data.crawled_at) }}
      </div>
      <div class="star-note">★ 表示相关动态中提及挂机/搬砖玩法</div>
    </div>

    <nav class="pub-nav">
      <button
        v-for="pub in publishers"
        :key="pub.key"
        :class="['pub-btn', { active: activePublisher === pub.key }]"
        @click="selectPublisher(pub.key)"
      >
        {{ pub.label }}
      </button>
    </nav>

    <section v-if="activeGroup" class="pub-section">
      <p v-if="activeGroup.games.length === 0" class="empty">该发行商暂无监测游戏</p>
      <div v-else class="card-grid">
        <div
          v-for="game in activeGroup.games"
          :key="game.game_name"
          class="game-card"
        >
          <span
            v-if="game.has_afk_grinding_tag"
            class="afk-star"
            title="相关动态中提及挂机/搬砖玩法"
          >★</span>

          <div class="card-top">
            <h3 class="game-name">{{ game.game_name }}</h3>
            <a
              class="official-link"
              :href="game.official_url"
              target="_blank"
              rel="noopener"
            >官网</a>
          </div>

          <!-- 待接入官方来源的游戏：仅提示占位 -->
          <p v-if="game.source_status === 'pending'" class="hint">
            官方来源待接入，暂只提供官网直达
          </p>
          <p v-else-if="game.source_status === 'error'" class="hint error-hint">
            本次采集失败，稍后重试
          </p>
          <p v-else-if="game.updates.length === 0" class="hint">
            近 {{ data.window_days }} 天暂无官方动态
          </p>

          <template v-else>
            <!-- 游戏卡片内部按动态类型（全部/更新公告/新活动/公告等）切换的小 Tab -->
            <nav class="type-nav">
              <button
                v-for="type in typesOf(game)"
                :key="type"
                :class="['type-btn', typeClass(type), { active: activeType(game) === type }]"
                @click="selectType(game, type)"
              >{{ type }}</button>
            </nav>

            <ul class="update-list">
              <li v-for="(u, i) in filteredUpdates(game)" :key="i" class="update-item">
                <div class="update-head">
                  <span :class="['type-tag', typeClass(u.type)]">{{ u.type }}</span>
                  <span class="update-date">{{ u.date }}</span>
                </div>
                <a
                  v-if="u.url"
                  class="update-title"
                  :href="u.url"
                  target="_blank"
                  rel="noopener"
                >{{ u.title }}</a>
                <span v-else class="update-title">{{ u.title }}</span>
                <p v-if="u.summary" class="update-summary">{{ u.summary }}</p>
              </li>
            </ul>
          </template>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.panel-meta {
  font-size: 12px;
  margin-bottom: 8px;
}

.panel-meta .source-line {
  color: #666;
}

.panel-meta .star-note {
  margin-top: 2px;
  color: #aaa;
}

.pub-nav {
  position: sticky;
  top: 0;
  background: #fafafa;
  padding: 8px 0;
  margin-bottom: 12px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  z-index: 5;
  border-bottom: 1px solid #eee;
}

.pub-btn {
  border: 1px solid #ddd;
  background: #fff;
  padding: 6px 12px;
  border-radius: 16px;
  font-size: 13px;
  cursor: pointer;
  color: #333;
}

.pub-btn:hover {
  border-color: #1976d2;
  color: #1976d2;
}

.pub-btn.active {
  background: #1976d2;
  color: #fff;
  border-color: #1976d2;
}

.pub-section {
  margin-bottom: 24px;
}

.empty {
  color: #999;
  font-size: 13px;
}

.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
}

.game-card {
  position: relative;
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  padding: 16px;
  background: #fff;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.afk-star {
  position: absolute;
  top: 8px;
  right: 10px;
  font-size: 20px;
  line-height: 1;
  color: #ffc107;
  text-shadow: 0 0 1px #e0a800;
}

.card-top {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 8px;
}

.game-name {
  margin: 0;
  font-size: 15px;
  line-height: 1.4;
}

.official-link {
  font-size: 12px;
  color: #1976d2;
  text-decoration: none;
  flex-shrink: 0;
}

.official-link:hover {
  text-decoration: underline;
}

.hint {
  margin: 0;
  font-size: 13px;
  color: #999;
}

.error-hint {
  color: #d32f2f;
}

.type-nav {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.type-btn {
  border: 1px solid #ddd;
  background: #fff;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 12px;
  cursor: pointer;
  /* tab 底色由下方 .type-xxx 类型色覆盖（同优先级、更靠后），统一用白字保证可读。
     字色统一成白色后，选中态无法再靠字色区分，改用整体透明度 + 字重区分，
     这样不需要改动各类型的底色值。 */
  color: #fff;
  opacity: 0.55;
}

.type-btn:hover {
  border-color: #1976d2;
  opacity: 0.85;
}

.type-btn.active {
  color: #fff;
  border-color: transparent;
  opacity: 1;
  font-weight: 700;
}

.type-btn.active.type-foresight {
  background: #7b1fa2;
}

.type-btn.active.type-activity {
  background: #ef6c00;
}

.type-btn.active.type-update {
  background: #1976d2;
}

.type-btn.active.type-esports {
  background: #00838f;
}

.type-btn.active.type-news {
  background: #546e7a;
}

.type-btn.active.type-warning {
  background: #c62828;
}

.type-btn.active.type-default {
  background: #757575;
}

/* 限高 350px 并在列表内滚动，避免单个游戏动态过多把整张卡片和页面拉得很长。
   单条动态高度随有无摘要浮动（约 46~76px），所以实际露出 3~5 条。 */
.update-list {
  list-style: none;
  margin: 0;
  padding: 0 6px 0 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-height: 350px;
  overflow-y: auto;
  overscroll-behavior: contain;
}

.update-list::-webkit-scrollbar {
  width: 6px;
}

.update-list::-webkit-scrollbar-thumb {
  background: #d0d0d0;
  border-radius: 3px;
}

.update-list::-webkit-scrollbar-thumb:hover {
  background: #b0b0b0;
}

.update-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  border-top: 1px solid #f0f0f0;
  padding-top: 10px;
}

.update-item:first-child {
  border-top: none;
  padding-top: 0;
}

.update-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.type-tag {
  font-size: 12px;
  padding: 1px 6px;
  border-radius: 3px;
  color: #fff;
  flex-shrink: 0;
}

.type-foresight {
  background: #7b1fa2;
}

.type-activity {
  background: #ef6c00;
}

.type-update {
  background: #1976d2;
}

/* 赛事：中性亮色 */
.type-esports {
  background: #00838f;
}

/* 公告 / 资讯 / 新闻：中性色 */
.type-news {
  background: #546e7a;
}

/* 安全公告 / 处罚公告：警示色 */
.type-warning {
  background: #c62828;
}

.type-default {
  background: #757575;
}

.update-date {
  font-size: 12px;
  color: #999;
}

.update-title {
  font-size: 13px;
  color: #222;
  line-height: 1.4;
  text-decoration: none;
  font-weight: 600;
}

a.update-title:hover {
  color: #1976d2;
  text-decoration: underline;
}

.update-summary {
  margin: 0;
  font-size: 12px;
  color: #666;
  line-height: 1.5;
}
</style>
