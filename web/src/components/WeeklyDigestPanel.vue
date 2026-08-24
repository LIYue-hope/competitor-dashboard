<script setup>
defineProps({
  data: { type: Object, default: null },
})

function formatGeneratedAt(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function weekLabel(data) {
  if (!data?.week_start || !data?.week_end) return ''
  return `${data.week_start} 至 ${data.week_end}`
}

function rankListsText(lists) {
  const map = { download: '下载榜', reserve: '预约榜', played: '热玩榜' }
  return (lists || []).map((key) => map[key] || key).join(' / ')
}

</script>

<template>
  <div class="weekly-panel">
    <p v-if="!data" class="summary-placeholder">暂无上周总结</p>
    <template v-else>
      <div class="panel-meta">
        <div class="source-line">
          {{ weekLabel(data) }} · {{ data.article_count }} 条资讯 · {{ data.game_count }} 款游戏
          <span v-if="data.generated_at"> · 更新于 {{ formatGeneratedAt(data.generated_at) }}</span>
        </div>
      </div>

      <p class="digest-text">{{ data.digest }}</p>
      <p v-if="data.heat_formula" class="heat-formula">{{ data.heat_formula }}</p>

      <p class="digest-subhead">综合热度榜</p>
      <ol v-if="data.hot_ranking?.length" class="rank-list">
        <li v-for="row in data.hot_ranking" :key="row.rank + row.name" class="rank-item">
          <p class="rank-head">
            <span class="rank-no">{{ row.rank }}</span>
            <span class="digest-game">{{ row.name }}</span>
            <span class="heat-score">热度 {{ row.heat_score }}</span>
          </p>
          <p class="rank-meta">
            资讯 {{ row.media_count }} 条 · {{ row.source_count }} 个来源
            <template v-if="row.reservation_label"> · 预约 {{ row.reservation_label }}</template>
            <template v-if="row.follow_label"> · 关注 {{ row.follow_label }}</template>
            <template v-if="row.best_rank"> · TapTap 最高第 {{ row.best_rank }}（{{ rankListsText(row.rank_lists) }}）</template>
            <template v-if="row.official_count"> · 官方动态 {{ row.official_count }}</template>
          </p>
          <ul v-if="row.news?.length" class="news-list">
            <li v-for="item in row.news" :key="item.url" class="news-item">
              <a class="news-title" :href="item.url" target="_blank" rel="noopener noreferrer">{{ item.title }}</a>
              <span class="news-meta">{{ item.source }} · {{ item.published_at }}</span>
            </li>
          </ul>
        </li>
      </ol>
      <p v-else class="empty">本周暂无达到入榜门槛的游戏</p>
    </template>
  </div>
</template>

<style scoped>
/* 外层卡片高度固定，这里吃掉剩余空间并自行滚动 */
.weekly-panel {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding-right: 6px;
}

.panel-meta {
  font-size: 12px;
  margin-bottom: 12px;
}

.source-line {
  color: #666;
}

.digest-text {
  margin: 0 0 6px;
  font-size: 13px;
  color: #333;
  line-height: 1.8;
  text-align: justify;
}

/* 热度口径属于注解，压到小字避免抢正文 */
.heat-formula {
  margin: 0 0 16px;
  font-size: 11px;
  color: #999;
  line-height: 1.7;
}

.digest-subhead {
  margin: 0 0 8px;
  font-size: 13px;
  font-weight: 600;
  color: #444;
}

.rank-list {
  margin: 0 0 16px;
  padding-left: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.rank-item {
  font-size: 13px;
  color: #333;
}

.rank-head {
  margin: 0 0 2px;
  font-weight: 600;
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.rank-no {
  color: #1976d2;
  min-width: 1.2em;
}

.heat-score {
  font-size: 12px;
  font-weight: 400;
  color: #999;
}

.rank-meta {
  margin: 0;
  font-weight: 400;
  line-height: 1.75;
  color: #444;
}

/* 每款游戏的代表资讯，缩进挂在该行下面 */
.news-list {
  margin: 4px 0 0;
  padding-left: 1.2em;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.news-item {
  font-size: 12px;
  line-height: 1.7;
}

.news-title {
  color: #1976d2;
  text-decoration: none;
}

.news-title:hover {
  text-decoration: underline;
}

.news-meta {
  margin-left: 6px;
  color: #999;
}

.empty,
.summary-placeholder {
  margin: 0;
  font-size: 13px;
  color: #aaa;
}
</style>
