<script setup>
import { ref, onMounted } from 'vue'
import GameCard from './components/GameCard.vue'
import HaoyouPanel from './components/HaoyouPanel.vue'
import JiuyouPanel from './components/JiuyouPanel.vue'
import HotGamesPanel from './components/HotGamesPanel.vue'
import GameNewsPanel from './components/GameNewsPanel.vue'
import RefreshButton from './components/RefreshButton.vue'


// 六个数据源分开加载与展示：
// - taptap_upcoming.json：TapTap 新游预约扁平列表
// - haoyoukuaibao_upcoming.json：好游快爆按日期分组的时间线
// - 9game_upcoming.json：九游新游开测按日期分组的时间线
// - hot_games_dynamics.json：热门游戏动态按发行商分组
// - 3dmgame_news.json / 3dmgame_reviews.json：游戏资讯（3DMGame 新闻 + 测评）
const taptapGames = ref([])
const haoyouData = ref(null)
const jiuyouData = ref(null)
const hotGamesData = ref(null)
const dmNewsData = ref(null)
const dmReviewsData = ref(null)
const taptapError = ref('')
const haoyouError = ref('')
const jiuyouError = ref('')
const hotGamesError = ref('')
const dmNewsError = ref('')
const dmReviewsError = ref('')
const loading = ref(true)

// 当前激活 Tab，默认 TapTap
const activeTab = ref('taptap')

async function loadJson(name) {
  // 使用 import.meta.env.BASE_URL 拼接数据路径，
  // 保证在 GitHub Pages 子路径（/competitor-dashboard/）部署下也能正确请求到 data/*.json
  const res = await fetch(`${import.meta.env.BASE_URL}data/${name}`)
  if (!res.ok) {
    throw new Error(`请求 ${name} 失败：${res.status}`)
  }
  return res.json()
}

onMounted(async () => {
  // 各数据源独立加载，一个失败不影响其它 Tab / 板块的可用性
  const [taptapResult, haoyouResult, jiuyouResult, hotGamesResult, dmNewsResult, dmReviewsResult] =
    await Promise.allSettled([
      loadJson('taptap_upcoming.json'),
      loadJson('haoyoukuaibao_upcoming.json'),
      loadJson('9game_upcoming.json'),
      loadJson('hot_games_dynamics.json'),
      loadJson('3dmgame_news.json'),
      loadJson('3dmgame_reviews.json'),
    ])


  if (taptapResult.status === 'fulfilled') {
    taptapGames.value = taptapResult.value
  } else {
    taptapError.value = `数据加载失败：${taptapResult.reason.message}`
  }

  if (haoyouResult.status === 'fulfilled') {
    haoyouData.value = haoyouResult.value
  } else {
    haoyouError.value = `数据加载失败：${haoyouResult.reason.message}`
  }

  if (jiuyouResult.status === 'fulfilled') {
    jiuyouData.value = jiuyouResult.value
  } else {
    jiuyouError.value = `数据加载失败：${jiuyouResult.reason.message}`
  }

  if (hotGamesResult.status === 'fulfilled') {
    hotGamesData.value = hotGamesResult.value
  } else {
    hotGamesError.value = `数据加载失败：${hotGamesResult.reason.message}`
  }

  if (dmNewsResult.status === 'fulfilled') {
    dmNewsData.value = dmNewsResult.value
  } else {
    dmNewsError.value = `数据加载失败：${dmNewsResult.reason.message}`
  }

  if (dmReviewsResult.status === 'fulfilled') {
    dmReviewsData.value = dmReviewsResult.value
  } else {
    dmReviewsError.value = `数据加载失败：${dmReviewsResult.reason.message}`
  }

  loading.value = false
})

// crawled_at 是采集脚本写入的 UTC 时间（ISO 8601 带时区偏移）。
// 按用户本地时区展示为"月-日 时:分"，不显示年份和秒。
function formatCrawledAt(isoString) {
  if (!isoString) return ''
  const d = new Date(isoString)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

// RefreshButton 只在三次抓取全部成功时才 emit，因此这里拿到的一定是校验过的完整数据，
// 直接整体替换对应板块的数据源即可；失败时不会走到这里，页面保留原有数据。
function onNewGamesRefreshed(payload) {
  taptapGames.value = payload['taptap_upcoming.json']
  haoyouData.value = payload['haoyoukuaibao_upcoming.json']
  jiuyouData.value = payload['9game_upcoming.json']
  taptapError.value = ''
  haoyouError.value = ''
  jiuyouError.value = ''
}

function onHotGamesRefreshed(payload) {
  hotGamesData.value = payload['hot_games_dynamics.json']
  hotGamesError.value = ''
}

function onNewsRefreshed(payload) {
  dmNewsData.value = payload['3dmgame_news.json']
  dmReviewsData.value = payload['3dmgame_reviews.json']
  dmNewsError.value = ''
  dmReviewsError.value = ''
}

</script>

<template>
  <div class="page">
    <header class="page-header">
      <h1>游戏行业监测看板</h1>
    </header>

    <h2 class="hot-heading">
      新游监测
      <RefreshButton
        :files="['taptap_upcoming.json', 'haoyoukuaibao_upcoming.json', '9game_upcoming.json']"
        storage-key="new-games"
        @refreshed="onNewGamesRefreshed"
      />
    </h2>


    <nav class="tab-nav">
      <button
        :class="['tab-btn', { active: activeTab === 'taptap' }]"
        @click="activeTab = 'taptap'"
      >TapTap</button>
      <button
        :class="['tab-btn', { active: activeTab === 'haoyou' }]"
        @click="activeTab = 'haoyou'"
      >好游快爆</button>
      <button
        :class="['tab-btn', { active: activeTab === 'jiuyou' }]"
        @click="activeTab = 'jiuyou'"
      >九游</button>
    </nav>

    <p v-if="loading">加载中...</p>

    <!-- TapTap Tab -->
    <section v-show="!loading && activeTab === 'taptap'" class="tab-panel">
      <p v-if="taptapError" class="error">{{ taptapError }}</p>
      <p v-else-if="taptapGames.length === 0">暂无数据</p>
      <template v-else>
        <div v-if="taptapGames[0]" class="panel-meta">
          <div class="source-line">数据来源：TapTap-即将上线  更新时间 {{ formatCrawledAt(taptapGames[0].crawled_at) }}</div>
          <div class="star-note">★ 表示该游戏的游戏介绍或开发者的话中提及挂机/搬砖玩法</div>
        </div>
        <div class="card-grid">
          <GameCard v-for="game in taptapGames" :key="game.source_url" :game="game" />
        </div>
      </template>
    </section>

    <!-- 好游快爆 Tab -->
    <section v-show="!loading && activeTab === 'haoyou'" class="tab-panel">
      <p v-if="haoyouError" class="error">{{ haoyouError }}</p>
      <p v-else-if="!haoyouData || haoyouData.days.length === 0">暂无数据</p>
      <HaoyouPanel v-else :data="haoyouData" />
    </section>

    <!-- 九游 Tab -->
    <section v-show="!loading && activeTab === 'jiuyou'" class="tab-panel">
      <p v-if="jiuyouError" class="error">{{ jiuyouError }}</p>
      <p v-else-if="!jiuyouData || jiuyouData.days.length === 0">暂无数据</p>
      <JiuyouPanel v-else :data="jiuyouData" />
    </section>

    <!-- 热门游戏动态监测：固定展示在新游监测 Tab 内容下方，不作为可切换的顶级 Tab -->
    <section v-if="!loading" class="hot-section">
      <h2 class="hot-heading">
        热门游戏动态监测
        <RefreshButton
          :files="['hot_games_dynamics.json']"
          storage-key="hot-games"
          @refreshed="onHotGamesRefreshed"
        />
      </h2>

      <p v-if="hotGamesError" class="error">{{ hotGamesError }}</p>
      <p v-else-if="!hotGamesData || hotGamesData.publishers.length === 0">暂无数据</p>
      <HotGamesPanel v-else :data="hotGamesData" />
    </section>

    <!-- 游戏资讯：与新游监测、热门游戏动态监测同级的独立板块，
         当前只接入 3DMGame，内部再分新闻 / 测评两个子 Tab -->
    <section v-if="!loading" class="hot-section">
      <h2 class="hot-heading">
        游戏资讯
        <RefreshButton
          :files="['3dmgame_news.json', '3dmgame_reviews.json']"
          storage-key="game-news"
          @refreshed="onNewsRefreshed"
        />
      </h2>

      <h3 class="sub-heading">3DMGame</h3>
      <GameNewsPanel
        :news-data="dmNewsData"
        :reviews-data="dmReviewsData"
        :news-error="dmNewsError"
        :reviews-error="dmReviewsError"
      />
    </section>
  </div>
</template>

<style scoped>
.page {
  max-width: 1080px;
  margin: 0 auto;
  padding: 24px 16px 48px;
}

.page-header {
  margin-bottom: 16px;
}

.page-header h1 {
  margin: 0 0 4px;
  font-size: 24px;
}

.tab-nav {
  display: flex;
  gap: 8px;
  margin-bottom: 20px;
  border-bottom: 1px solid #e0e0e0;
}

.tab-btn {
  border: none;
  background: none;
  padding: 8px 16px;
  font-size: 14px;
  cursor: pointer;
  color: #555;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
}

.tab-btn:hover {
  color: #1976d2;
}

.tab-btn.active {
  color: #1976d2;
  border-bottom-color: #1976d2;
  font-weight: 600;
}

/* 两个 Tab 面板统一容器盒模型（无边距差异），
   保证切换 Tab 时内容区域起始位置一致，不出现页面偏移 */
.tab-panel {
  min-height: 0;
  padding: 0;
  margin: 0;
}

.error {
  color: #d32f2f;
}

.panel-meta {
  font-size: 12px;
  margin-bottom: 12px;
}

.panel-meta .source-line {
  color: #666;
}

.panel-meta .star-note {
  margin-top: 2px;
  color: #aaa;
}

.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 16px;
}

.hot-section {
  margin-top: 32px;
  padding-top: 20px;
  border-top: 1px solid #e0e0e0;
}

.hot-heading {
  font-size: 18px;
  margin: 0 0 16px;
  color: #222;
}

.sub-heading {
  font-size: 15px;
  margin: 0 0 12px;
  color: #444;
}

</style>
