<script setup>
import { ref, onMounted } from 'vue'
import GameCard from './components/GameCard.vue'

const games = ref([])
const loading = ref(true)
const error = ref('')

onMounted(async () => {
  try {
    const res = await fetch('/data/taptap_upcoming.json')
    if (!res.ok) {
      throw new Error(`请求失败：${res.status}`)
    }
    games.value = await res.json()
  } catch (e) {
    error.value = `数据加载失败：${e.message}`
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="page">
    <header class="page-header">
      <h1>TapTap 新游监测</h1>
      <p class="subtitle">竞品看板 · 数据来源：TapTap 新游预约页</p>
    </header>

    <p v-if="loading">加载中...</p>
    <p v-else-if="error" class="error">{{ error }}</p>
    <p v-else-if="games.length === 0">暂无数据</p>

    <div v-else class="card-grid">
      <GameCard v-for="game in games" :key="game.source_url" :game="game" />
    </div>
  </div>
</template>

<style scoped>
.page {
  max-width: 1080px;
  margin: 0 auto;
  padding: 24px 16px 48px;
}

.page-header {
  margin-bottom: 24px;
}

.page-header h1 {
  margin: 0 0 4px;
  font-size: 24px;
}

.subtitle {
  margin: 0;
  color: #666;
  font-size: 14px;
}

.error {
  color: #d32f2f;
}

.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 16px;
}
</style>
