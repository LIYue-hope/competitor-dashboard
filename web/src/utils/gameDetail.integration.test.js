import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { buildGameIndex, getGameDetail } from './gameDetail.js'
import { resolveGameKey } from './gameIdentity.js'

const files = {
  weekly: 'weekly_digest', weeklyHistory: 'weekly_history', taptap: 'taptap_upcoming',
  haoyou: 'haoyoukuaibao_upcoming', jiuyou: '9game_upcoming', p16: '16p_upcoming',
  hot: 'hot_games_dynamics', dmNews: '3dmgame_news', dmReviews: '3dmgame_reviews',
  yxNews: 'youxia_news', yxReviews: 'youxia_reviews', gsNews: 'gamersky_news',
  gsReviews: 'gamersky_reviews', glNews: 'gamelook_news', grNews: 'gameres_news',
}
const data = Object.fromEntries(Object.entries(files).map(([key, file]) => [key,
  JSON.parse(readFileSync(new URL(`../../../data/${file}.json`, import.meta.url), 'utf8')),
]))
const index = buildGameIndex(data, {}, { today: '9999-12-31' })

test('real full history ledger provides every valid game including rows outside ranking', () => {
  const ranking = new Set(data.weeklyHistory.news_ranking.map(row => row.name))
  const outside = data.weeklyHistory.news_history.filter(row => !ranking.has(row.name) && resolveGameKey(row.name))
  assert.ok(outside.length > 0)
  for (const row of outside) {
    const cumulative = getGameDetail(index, row.name)?.history.cumulativeNews
    assert.ok(cumulative, row.name)
    assert.ok(cumulative.records.some(record => record.name === row.name && record.media_count === row.media_count), row.name)
  }
})

test('real date-only schedules and official records survive Beijing date normalization', () => {
  for (const row of data.taptap.filter(row => row.release_date && resolveGameKey(row.game_name))) {
    assert.ok(getGameDetail(index, row.game_name).schedules.some(schedule => schedule.date === row.release_date), row.game_name)
  }
  for (const publisher of data.hot.publishers) for (const row of publisher.games) {
    if (!resolveGameKey(row.game_name)) continue
    const detail = getGameDetail(index, row.game_name)
    if (row.source_status === 'error') {
      assert.ok(detail.sourceStates.some(state => state.key.startsWith('official:') && state.status === 'error'), row.game_name)
    } else {
      for (const update of row.updates || []) assert.ok(detail.officialUpdates.some(item => item.url === update.url), row.game_name)
    }
  }
})

test('real partial source failure preserves data from other feeds', () => {
  const partial = buildGameIndex(data, { dmNews: '独立测试模拟请求失败', weekly: '独立测试模拟请求失败' }, { today: '9999-12-31' })
  for (const [key, detail] of partial) {
    assert.equal(detail.history.latestWeekly, null, key)
    assert.equal(detail.articles.some(article => article.source === '3dm' && article.type === 'news'), false, key)
    assert.equal(detail.sourceStates.find(state => state.key === 'dmNews').status, 'error', key)
  }
  assert.ok([...partial.values()].some(detail => detail.articles.some(article => article.source !== '3dm')))
})
