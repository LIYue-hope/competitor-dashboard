<script setup>
import { computed } from 'vue'

// TapTap / 好游快爆 / 九游 三个来源共用同一张卡片：字段有多有少，缺的行直接不渲染。
const props = defineProps({
  game: {
    type: Object,
    required: true,
  },
})

const url = computed(() => props.game.source_url || props.game.detail_url || '')

const rows = computed(() => {
  const g = props.game
  return [
    ['发行商', g.publisher],
    // TapTap 给 release_date（上线日期），好游快爆给 event_desc（当日事件描述）
    ['上线', g.release_date || g.event_desc],
    ['类型', (g.categories || []).join('、')],
    // 预约量与关注量是两个不同口径，标签跟着实际字段走，别混成一个"预约"
    [g.reservation_count ? '预约' : '关注', g.reservation_count || g.follow_count],
  ].filter(([, v]) => v)
})
</script>

<template>
  <article class="g-card">
    <div class="g-top">
      <h3 class="g-name">
        <a v-if="url" :href="url" target="_blank" rel="noopener">{{ game.game_name || '未知游戏' }}</a>
        <template v-else>{{ game.game_name || '未知游戏' }}</template>
      </h3>
      <span v-if="game.score" class="g-score">{{ game.score }}</span>
    </div>

    <dl class="g-rows">
      <template v-for="[k, v] in rows" :key="k">
        <dt>{{ k }}</dt>
        <dd>{{ v }}</dd>
      </template>
    </dl>

    <div v-if="game.is_major_publisher || game.has_afk_grinding_tag || game.status_tag" class="g-tags">
      <span v-if="game.is_major_publisher" class="badge brand">大厂/大IP</span>
      <span
        v-if="game.has_afk_grinding_tag"
        class="badge star"
        title="游戏介绍或开发者的话中提及挂机/搬砖玩法"
      >★ 挂机/搬砖</span>
      <span v-if="game.status_tag" class="badge">{{ game.status_tag }}</span>
    </div>
  </article>
</template>

<style scoped>
.g-card {
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  background: var(--surface);
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  transition: transform .12s, box-shadow .12s, border-color .12s;
}

.g-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-2);
  border-color: var(--border-strong);
}

.g-top { display: flex; align-items: flex-start; gap: 8px; }

.g-name {
  margin: 0;
  font-size: 14.5px;
  font-weight: 650;
  line-height: 1.35;
  flex: 1;
}

.g-name a { text-decoration: none; }
.g-name a:hover { color: var(--brand); }

.g-score {
  font-size: 13px;
  font-weight: 700;
  color: var(--warn);
  font-variant-numeric: tabular-nums;
  flex: none;
}

.g-rows {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 4px 10px;
  margin: 0;
  font-size: 12.5px;
}

.g-rows dt { color: var(--text-3); margin: 0; }
.g-rows dd { margin: 0; color: var(--text-2); }

.g-tags { display: flex; flex-wrap: wrap; gap: 5px; }
</style>
