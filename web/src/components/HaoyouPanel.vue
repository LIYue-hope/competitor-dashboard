<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  data: {
    type: Object,
    required: true,
    // { crawled_at, days: [ {date, date_label, games: [...] } ] }
  },
})

// 当前激活的日期。默认选中第一条日期分组。
const activeDate = ref(props.data.days?.[0]?.date || '')

const days = computed(() => props.data.days || [])

// 当前选中日期对应的分组数据，供模板只渲染这一组，不再滚动定位到其它分组
const activeDay = computed(
  () => days.value.find((day) => day.date === activeDate.value) || null
)

function selectDate(date) {
  activeDate.value = date
}

function formatCrawledAt(isoString) {
  if (!isoString) return ''
  const d = new Date(isoString)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
</script>

<template>
  <div class="haoyou-panel">
    <div v-if="data.crawled_at" class="panel-meta">
      <div class="source-line">数据来源：好游快爆-即将上线  更新时间 {{ formatCrawledAt(data.crawled_at) }}</div>
      <div class="star-note">★ 表示该游戏的游戏介绍或开发者的话中提及挂机/搬砖玩法</div>
    </div>

    <nav class="date-nav">
      <button
        v-for="day in days"
        :key="day.date"
        :class="['date-btn', { active: activeDate === day.date }]"
        @click="selectDate(day.date)"
      >
        {{ day.date_label }}
      </button>
    </nav>

    <section v-if="activeDay" class="date-section">
      <h2 class="date-heading">{{ activeDay.date_label }}</h2>
      <p v-if="activeDay.games.length === 0" class="empty">当日无排期</p>
      <div v-else class="card-grid">
        <div v-for="game in activeDay.games" :key="game.game_name" class="game-card">
          <div class="card-top">
            <h3 class="game-name">{{ game.game_name }}</h3>
            <span class="score-group">
              <span
                v-if="game.has_afk_grinding_tag"
                class="afk-star"
                title="游戏介绍或开发者的话中提及挂机/搬砖玩法"
              >★</span>
              <span v-if="game.score" class="score">{{ game.score }}</span>
            </span>
          </div>
          <dl class="info-list">
            <div class="info-row">
              <dt>发行商</dt>
              <dd>{{ game.publisher || '未知' }}</dd>
            </div>
            <div class="info-row">
              <dt>类型</dt>
              <dd>{{ (game.categories && game.categories.join('、')) || '未知' }}</dd>
            </div>
            <div class="info-row">
              <dt>预约量级</dt>
              <dd>{{ game.reservation_count || '未知' }}</dd>
            </div>
          </dl>
          <p v-if="game.event_desc" class="event-desc">{{ game.event_desc }}</p>
          <div v-if="game.status_tag" class="status-tag">{{ game.status_tag }}</div>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.panel-meta {
  color: #aaa;
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

.date-nav {
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

.date-btn {
  border: 1px solid #ddd;
  background: #fff;
  padding: 6px 12px;
  border-radius: 16px;
  font-size: 13px;
  cursor: pointer;
  color: #333;
}

.date-btn:hover {
  border-color: #1976d2;
  color: #1976d2;
}

.date-btn.active {
  background: #1976d2;
  color: #fff;
  border-color: #1976d2;
}

.date-section {
  margin-bottom: 24px;
}

.date-heading {
  font-size: 16px;
  margin: 0 0 12px;
  color: #333;
  border-left: 3px solid #1976d2;
  padding-left: 8px;
}

.empty {
  color: #999;
  font-size: 13px;
}

.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
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
  gap: 8px;
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

.score-group {
  display: flex;
  align-items: baseline;
  gap: 4px;
  flex-shrink: 0;
}

.afk-star {
  font-size: 16px;
  line-height: 1;
  color: #ffc107;
  text-shadow: 0 0 1px #e0a800;
}

.score {
  font-size: 14px;
  color: #ff9800;
  font-weight: bold;
}

.info-list {
  margin: 0;
}

.info-row {
  display: flex;
  font-size: 13px;
  color: #333;
  margin-bottom: 4px;
}

.info-row dt {
  width: 64px;
  color: #888;
  flex-shrink: 0;
}

.info-row dd {
  margin: 0;
}

.event-desc {
  margin: 0;
  font-size: 13px;
  color: #444;
  line-height: 1.5;
}

.status-tag {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 4px;
  color: #fff;
  background: #757575;
  align-self: flex-start;
}
</style>
