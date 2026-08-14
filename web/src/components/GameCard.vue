<script setup>
defineProps({
  game: {
    type: Object,
    required: true,
  },
})

// crawled_at 是采集脚本写入的 UTC 时间（ISO 8601 带时区偏移，如
// "...+00:00"）。这里按用户本地时区（浏览器所在时区）展示，格式为
// "月-日-时-分"，不显示年份和秒。若用户本地时区恰好是 UTC+8（北京时间），
// 显示结果会与北京时间一致；否则会按用户所在时区自动换算，避免误导。
function formatCrawledAt(isoString) {
  if (!isoString) return ''
  const date = new Date(isoString)
  if (Number.isNaN(date.getTime())) return ''
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())}-${pad(date.getHours())}-${pad(date.getMinutes())}`
}
</script>

<template>
  <div class="game-card">
    <div class="card-top">
      <h2 class="game-name">{{ game.game_name || '未知游戏' }}</h2>
      <span v-if="game.score" class="score">{{ game.score }}</span>
    </div>

    <dl class="info-list">
      <div class="info-row">
        <dt>发行商</dt>
        <dd>{{ game.publisher || '未知' }}</dd>
      </div>
      <div class="info-row">
        <dt>上线日期</dt>
        <dd>
          {{ game.release_date || '未知' }}
          <span v-if="game.crawled_at" class="crawled-at">
            更新于 {{ formatCrawledAt(game.crawled_at) }}
          </span>
        </dd>
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

    <div class="tags">
      <span v-if="game.is_major_publisher" class="tag tag-major">大厂/大IP</span>
      <span v-if="game.has_afk_grinding_tag" class="tag tag-afk">挂机/搬砖</span>
    </div>
  </div>
</template>

<style scoped>
.game-card {
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  padding: 16px;
  background: #fff;
}

.card-top {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 8px;
}

.game-name {
  margin: 0;
  font-size: 16px;
}

.score {
  font-size: 14px;
  color: #ff9800;
  font-weight: bold;
}

.info-list {
  margin: 0 0 12px;
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

.crawled-at {
  font-size: 11px;
  color: #aaa;
  margin-left: 4px;
}

.tags {
  display: flex;
  gap: 6px;
}

.tag {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 4px;
  color: #fff;
}

.tag-major {
  background: #1976d2;
}

.tag-afk {
  background: #757575;
}
</style>
