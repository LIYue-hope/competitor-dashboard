<script setup>
import { ref, onMounted } from 'vue'
import GameCard from './components/GameCard.vue'
import HaoyouPanel from './components/HaoyouPanel.vue'
import JiuyouPanel from './components/JiuyouPanel.vue'
import HotGamesPanel from './components/HotGamesPanel.vue'
import GameNewsPanel from './components/GameNewsPanel.vue'
import RefreshButton from './components/RefreshButton.vue'
import WeeklyDigestPanel from './components/WeeklyDigestPanel.vue'


// 各数据源分开加载与展示：
// - taptap_upcoming.json：TapTap 新游预约扁平列表
// - haoyoukuaibao_upcoming.json：好游快爆按日期分组的时间线
// - 9game_upcoming.json：九游新游开测按日期分组的时间线
// - hot_games_dynamics.json：热门游戏动态按发行商分组
// - 3dmgame_news.json / 3dmgame_reviews.json：游戏资讯（3DMGame 新闻 + 测评）
// - youxia_news.json / youxia_reviews.json：游戏资讯（游侠网 新闻 + 评测）
// - gamersky_news.json / gamersky_reviews.json：游戏资讯（游民星空 新闻 + 评测）
// - gamelook_news.json：游戏资讯（GameLook 新闻，该站只有新闻没有评测）
// - <来源>_digest.json：四个资讯源各自的每日新闻总结
const taptapGames = ref([])
const haoyouData = ref(null)
const jiuyouData = ref(null)
const hotGamesData = ref(null)
const dmNewsData = ref(null)
const dmReviewsData = ref(null)
const dmDigestData = ref(null)
const youxiaNewsData = ref(null)
const youxiaReviewsData = ref(null)
const youxiaDigestData = ref(null)
const gamerskyNewsData = ref(null)
const gamerskyReviewsData = ref(null)
const gamerskyDigestData = ref(null)
const gamelookNewsData = ref(null)
const gamelookDigestData = ref(null)
const taptapError = ref('')
const haoyouError = ref('')
const jiuyouError = ref('')
const hotGamesError = ref('')
const dmNewsError = ref('')
const dmReviewsError = ref('')
const dmDigestError = ref('')
const youxiaNewsError = ref('')
const youxiaReviewsError = ref('')
const youxiaDigestError = ref('')
const gamerskyNewsError = ref('')
const gamerskyReviewsError = ref('')
const gamerskyDigestError = ref('')
const gamelookNewsError = ref('')
const gamelookDigestError = ref('')
const weeklyData = ref(null)
const weeklyError = ref('')

const loading = ref(true)

// 顶层激活板块，默认新游监测。三个板块互斥显示，用 v-show 保留已加载 DOM
const activeSection = ref('new-games')

// 新游监测板块内部的二级 Tab，默认 TapTap
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
  const [
    taptapResult,
    haoyouResult,
    jiuyouResult,
    hotGamesResult,
    dmNewsResult,
    dmReviewsResult,
    dmDigestResult,
    youxiaNewsResult,
    youxiaReviewsResult,
    youxiaDigestResult,
    gamerskyNewsResult,
    gamerskyReviewsResult,
    gamerskyDigestResult,
    gamelookNewsResult,
    gamelookDigestResult,
    weeklyResult,
  ] =
    await Promise.allSettled([
      loadJson('taptap_upcoming.json'),
      loadJson('haoyoukuaibao_upcoming.json'),
      loadJson('9game_upcoming.json'),
      loadJson('hot_games_dynamics.json'),
      loadJson('3dmgame_news.json'),
      loadJson('3dmgame_reviews.json'),
      loadJson('3dmgame_digest.json'),
      loadJson('youxia_news.json'),
      loadJson('youxia_reviews.json'),
      loadJson('youxia_digest.json'),
      loadJson('gamersky_news.json'),
      loadJson('gamersky_reviews.json'),
      loadJson('gamersky_digest.json'),
      loadJson('gamelook_news.json'),
      loadJson('gamelook_digest.json'),
      loadJson('weekly_digest.json'),
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

  if (dmDigestResult.status === 'fulfilled') {
    dmDigestData.value = dmDigestResult.value
  } else {
    dmDigestError.value = `数据加载失败：${dmDigestResult.reason.message}`
  }


  if (youxiaNewsResult.status === 'fulfilled') {
    youxiaNewsData.value = youxiaNewsResult.value
  } else {
    youxiaNewsError.value = `数据加载失败：${youxiaNewsResult.reason.message}`
  }

  if (youxiaReviewsResult.status === 'fulfilled') {
    youxiaReviewsData.value = youxiaReviewsResult.value
  } else {
    youxiaReviewsError.value = `数据加载失败：${youxiaReviewsResult.reason.message}`
  }

  if (youxiaDigestResult.status === 'fulfilled') {
    youxiaDigestData.value = youxiaDigestResult.value
  } else {
    youxiaDigestError.value = `数据加载失败：${youxiaDigestResult.reason.message}`
  }

  if (gamerskyNewsResult.status === 'fulfilled') {
    gamerskyNewsData.value = gamerskyNewsResult.value
  } else {
    gamerskyNewsError.value = `数据加载失败：${gamerskyNewsResult.reason.message}`
  }

  if (gamerskyReviewsResult.status === 'fulfilled') {
    gamerskyReviewsData.value = gamerskyReviewsResult.value
  } else {
    gamerskyReviewsError.value = `数据加载失败：${gamerskyReviewsResult.reason.message}`
  }

  if (gamerskyDigestResult.status === 'fulfilled') {
    gamerskyDigestData.value = gamerskyDigestResult.value
  } else {
    gamerskyDigestError.value = `数据加载失败：${gamerskyDigestResult.reason.message}`
  }

  if (gamelookNewsResult.status === 'fulfilled') {
    gamelookNewsData.value = gamelookNewsResult.value
  } else {
    gamelookNewsError.value = `数据加载失败：${gamelookNewsResult.reason.message}`
  }

  if (gamelookDigestResult.status === 'fulfilled') {
    gamelookDigestData.value = gamelookDigestResult.value
  } else {
    gamelookDigestError.value = `数据加载失败：${gamelookDigestResult.reason.message}`
  }




  if (weeklyResult.status === 'fulfilled') {
    weeklyData.value = weeklyResult.value
  } else {
    weeklyError.value = weeklyResult.reason.message
      ? `数据加载失败：${weeklyResult.reason.message}`
      : '数据加载失败'
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

function onWeeklyRefreshed(payload) {
  weeklyData.value = payload['weekly_digest.json']
  weeklyError.value = ''
}

function onNewsRefreshed(payload) {
  dmNewsData.value = payload['3dmgame_news.json']
  dmReviewsData.value = payload['3dmgame_reviews.json']
  dmDigestData.value = payload['3dmgame_digest.json']
  youxiaNewsData.value = payload['youxia_news.json']
  youxiaReviewsData.value = payload['youxia_reviews.json']
  youxiaDigestData.value = payload['youxia_digest.json']
  gamerskyNewsData.value = payload['gamersky_news.json']
  gamerskyReviewsData.value = payload['gamersky_reviews.json']
  gamerskyDigestData.value = payload['gamersky_digest.json']
  gamelookNewsData.value = payload['gamelook_news.json']
  gamelookDigestData.value = payload['gamelook_digest.json']
  dmNewsError.value = ''
  dmReviewsError.value = ''
  dmDigestError.value = ''
  youxiaNewsError.value = ''
  youxiaReviewsError.value = ''
  youxiaDigestError.value = ''
  gamerskyNewsError.value = ''
  gamerskyReviewsError.value = ''
  gamerskyDigestError.value = ''
  gamelookNewsError.value = ''
  gamelookDigestError.value = ''
}


</script>

<template>
  <div class="page">
    <header class="page-header">
      <h1>游戏行业监测看板</h1>
    </header>

    <!-- 上周游戏总结：预留占位模块，本次不接数据 -->
        <section class="summary-card">
      <h2 class="hot-heading">
        上周游戏总结
        <RefreshButton
          :files="['weekly_digest.json']"
          storage-key="weekly-digest"
          @refreshed="onWeeklyRefreshed"
        />
      </h2>
      <p v-if="weeklyError" class="error">{{ weeklyError }}</p>
      <WeeklyDigestPanel v-else :data="weeklyData" />
    </section>

    <!-- 顶层板块 Tab：新游监测 / 热门游戏动态监测 / 游戏资讯，三者互斥显示 -->
    <nav class="section-nav">
      <button
        :class="['section-btn', { active: activeSection === 'new-games' }]"
        @click="activeSection = 'new-games'"
      >新游监测</button>
      <button
        :class="['section-btn', { active: activeSection === 'hot-games' }]"
        @click="activeSection = 'hot-games'"
      >热门游戏动态监测</button>
      <button
        :class="['section-btn', { active: activeSection === 'news' }]"
        @click="activeSection = 'news'"
      >游戏资讯</button>
    </nav>

    <p v-if="loading">加载中...</p>

    <!-- 新游监测板块：内部再按 TapTap / 好游快爆 / 九游 分二级 Tab -->
    <section v-show="!loading && activeSection === 'new-games'" class="section-panel">
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
    </section>

    <!-- 热门游戏动态监测板块 -->
    <section v-show="!loading && activeSection === 'hot-games'" class="section-panel">
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

    <!-- 游戏资讯板块：已接入 3DMGame / 游侠网 / 游民星空 / GameLook，每个来源内部再分
         新闻 / 新闻总结 / 测评（评测）子 Tab，GameLook 没有评测所以只有前两个 -->
    <section v-show="!loading && activeSection === 'news'" class="section-panel">
      <h2 class="hot-heading">
        游戏资讯
        <RefreshButton
          :files="[
            '3dmgame_news.json',
            '3dmgame_reviews.json',
            '3dmgame_digest.json',
            'youxia_news.json',
            'youxia_reviews.json',
            'youxia_digest.json',
            'gamersky_news.json',
            'gamersky_reviews.json',
            'gamersky_digest.json',
            'gamelook_news.json',
            'gamelook_digest.json',
          ]"
          storage-key="game-news"
          @refreshed="onNewsRefreshed"
        />
      </h2>

      <div class="source-card">
        <h3 class="sub-heading">3DMGame</h3>
        <GameNewsPanel
          :news-data="dmNewsData"
          :reviews-data="dmReviewsData"
          :news-error="dmNewsError"
          :reviews-error="dmReviewsError"
          :digest-data="dmDigestData"
          :digest-error="dmDigestError"
          :show-digest="true"
          source-name="3DMGame"
          review-label="测评"
        />
      </div>

      <div class="source-card">
        <h3 class="sub-heading">游侠网</h3>
        <GameNewsPanel
          :news-data="youxiaNewsData"
          :reviews-data="youxiaReviewsData"
          :news-error="youxiaNewsError"
          :reviews-error="youxiaReviewsError"
          :digest-data="youxiaDigestData"
          :digest-error="youxiaDigestError"
          :show-digest="true"
          source-name="游侠网"
          review-label="评测"
          news-note="游侠网游戏频道更新滞后约 1 天，当天内容由全站资讯补齐，因此可能夹带少量非游戏资讯——这是为避免漏掉当天新闻的有意取舍，不是采集错误，滞后内容会在次日采集时自动校正。"
        />
      </div>

      <div class="source-card">
        <h3 class="sub-heading">游民星空</h3>
        <GameNewsPanel
          :news-data="gamerskyNewsData"
          :reviews-data="gamerskyReviewsData"
          :news-error="gamerskyNewsError"
          :reviews-error="gamerskyReviewsError"
          :digest-data="gamerskyDigestData"
          :digest-error="gamerskyDigestError"
          :show-digest="true"
          source-name="游民星空"
          review-label="评测"
          news-note="游民星空新闻合并「单机电玩 / NS / 手游 / 网游」四个频道；其中手游频道站点自 2026-07-31 起未再更新，10 天窗口内为 0 条，非抓取问题。"
        />
      </div>

      <div class="source-card">
        <h3 class="sub-heading">GameLook</h3>
        <GameNewsPanel
          :news-data="gamelookNewsData"
          :news-error="gamelookNewsError"
          :digest-data="gamelookDigestData"
          :digest-error="gamelookDigestError"
          :show-digest="true"
          source-name="GameLook"
          :show-reviews="false"
        />
      </div>
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

/* 上周游戏总结占位卡，视觉语言与 .source-card 一致 */
.summary-card {
  border: 1px solid #e0e0e0;
  border-radius: 6px;
  padding: 16px;
  margin-bottom: 20px;
  background: #fff;
  /* 固定 450px 高度，内容超出时由面板内部滚动 */
  height: 450px;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
}

.summary-card .hot-heading {
  margin-bottom: 8px;
  flex-shrink: 0;
}

.summary-placeholder {
  margin: 0;
  font-size: 13px;
  color: #aaa;
}

/* 顶层板块 Tab：比二级 .tab-btn 更醒目，用整块按钮 + 选中反色 */
.section-nav {
  display: flex;
  gap: 8px;
  margin-bottom: 20px;
}

.section-btn {
  border: 1px solid #e0e0e0;
  border-radius: 6px;
  background: #fff;
  padding: 10px 20px;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  color: #555;
}

.section-btn:hover {
  color: #1976d2;
  border-color: #1976d2;
}

.section-btn.active {
  color: #fff;
  background: #1976d2;
  border-color: #1976d2;
}

/* 三个顶层板块面板统一容器盒模型（不加 margin / 分割线），
   保证切换板块时内容区域起始位置一致，不出现页面偏移 */
.section-panel {
  min-height: 0;
  padding: 0;
  margin: 0;
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

/* 三个二级 Tab 面板统一容器盒模型（无边距差异），
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

/* 游戏资讯下各来源单独成卡，用与占位卡同色的细线框出边界，
   避免四个站的新闻列表在视觉上连成一片 */
.source-card {
  border: 1px solid #e0e0e0;
  border-radius: 6px;
  padding: 16px;
  margin-bottom: 16px;
  background: #fff;
}

.source-card:last-child {
  margin-bottom: 0;
}


</style>
