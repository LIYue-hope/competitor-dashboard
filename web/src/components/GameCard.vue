<script setup>
defineProps({
  game: {
    type: Object,
    required: true,
  },
})
</script>

<template>
  <div class="game-card">
    <div class="card-top">
      <h2 class="game-name">{{ game.game_name || '未知游戏' }}</h2>
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
        <dt>上线日期</dt>
        <dd>{{ game.release_date || '未知' }}</dd>
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
    </div>
  </div>
</template>

<style scoped>
.game-card {
  position: relative;
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
  gap: 8px;
}

.game-name {
  margin: 0;
  font-size: 16px;
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
</style>
