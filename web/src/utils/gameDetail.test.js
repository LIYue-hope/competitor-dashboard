import test from 'node:test'
import assert from 'node:assert/strict'
import { beijingDate, buildGameIndex, getGameDetail } from './gameDetail.js'

test('Beijing dates are explicit, timezone independent and reject impossible days', () => {
  assert.equal(beijingDate('2026-10-02 23:30:00'), '2026-10-02 23:30:00')
  assert.equal(beijingDate('2026-10-02T18:30:00Z'), '2026-10-03 02:30:00')
  assert.equal(beijingDate('2026-10-03'), '2026-10-03')
  assert.equal(beijingDate('2026-02-30'), '')
  assert.equal(beijingDate('2026-02-30T10:00:00Z'), '')
  assert.equal(beijingDate('2026-13-01'), '')
  assert.equal(beijingDate('2026-10-03 03:30:00'), '2026-10-03 03:30:00')
})

test('all feeds merge exact aliases, articles dedupe and conflicting schedules survive', () => {
  const news = { game_name: '原神', title: '新闻', published_at: '2026-10-02', url: 'https://same.test/a' }
  const data = {
    dmNews: { items: [news, news, { ...news, url: '', title: '同标题' }, { ...news, url: 'future', published_at: '2027-01-01' }] },
    yxNews: { items: [{ ...news, game_name: 'Genshin Impact' }, { ...news, url: '', title: '同标题' }] },
    dmReviews: { items: [{ title: '《原神》评测', published_at: '2026-10-01', url: 'https://review.test' }] },
    taptap: [{ game_name: '原神', release_date: '2027-01-01', status_tag: '首发', source_url: 'https://tap.test', crawled_at: '2026-10-03', score: '9.1' }],
    jiuyou: { days: [{ date: '2027-01-01', games: [{ game_name: 'Genshin Impact', status_tag: '首发', detail_url: 'https://nine.test' }] }, { date: '2027-01-02', games: [{ game_name: '原神', status_tag: '首发' }] }] },
    hot: { publishers: [{ label: '米哈游', games: [{ game_name: '原神', source_status: 'error', error: '官网异常' }] }] },
    weekly: { week_start: '2026-09-21', week_end: '2026-09-27', hot_ranking: [{ name: '原神', rank: 4, heat_score: 12 }] },
    weeklyHistory: { heat_ranking: [{ name: '原神', heat_score: 11 }, { name: 'Genshin Impact', heat_score: 22 }], news_ranking: [], news_history: [{ name: '原神', media_count: 2, article_ids: ['a', 'b'], first_article_date: '2026-08-31', last_article_date: '2026-09-20' }, { name: 'Genshin Impact', media_count: 2, article_ids: ['b', 'c'], first_article_date: '2026-09-01', last_article_date: '2026-10-02' }] },
  }
  const detail = getGameDetail(buildGameIndex(data, { gsNews: '请求失败' }, { today: '2026-10-03' }), 'genshin-impact')
  assert.equal(detail.articles.length, 4)
  assert.equal(detail.schedules.length, 2)
  assert.equal(detail.schedules.find((row) => row.date === '2027-01-01').sources.length, 2)
  assert.equal(detail.history.latestWeekly.rank, 4)
  assert.equal(detail.history.peakWeekly.heat_score, 22)
  assert.equal(detail.history.cumulativeNews.media_count, 3)
  assert.equal(detail.history.cumulativeNews.first_article_date, '2026-08-31')
  assert.equal(detail.sourceStates.find((row) => row.key === 'gsNews').status, 'error')
  assert.equal(detail.sourceStates.find((row) => row.source === 'official').error, '官网异常')
  assert.deepEqual(detail.profiles[0].platforms, [])
  assert.equal(getGameDetail(buildGameIndex(data), '原神2'), null)
})

test('cumulative data outside top 100 remains available; incomplete alias IDs stay separate', () => {
  const index = buildGameIndex({ weeklyHistory: { news_ranking: [], news_history: [
    { name: '榜外游戏', media_count: 3 }, { name: '原神', media_count: 10 },
    { name: 'Genshin Impact', media_count: 4, article_ids: ['a'] },
  ] } })
  assert.equal(getGameDetail(index, '榜外游戏').history.cumulativeNews.media_count, 3)
  const cumulative = getGameDetail(index, '原神').history.cumulativeNews
  assert.equal(cumulative.media_count, null)
  assert.equal(cumulative.separateRecords, true)
  assert.equal(cumulative.records.length, 2)
})

test('new index reflects refreshed data and never mutates source rows', () => {
  const data = { dmNews: { items: [{ game_name: 'Some GAME', title: 'one', published_at: '2026-10-02' }] } }
  const before = JSON.stringify(data)
  const first = buildGameIndex(data, {}, { today: '2026-10-03' })
  assert.equal(getGameDetail(first, 'some game').name, 'Some GAME')
  assert.equal(JSON.stringify(data), before)
  data.dmNews.items.push({ game_name: 'some game', title: 'two', published_at: '2026-10-03' })
  assert.equal(getGameDetail(buildGameIndex(data, {}, { today: '2026-10-03' }), 'some game').articles.length, 2)
})
