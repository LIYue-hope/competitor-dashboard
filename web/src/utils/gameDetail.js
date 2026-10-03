import { normalizeGameName, resolveGameKey, getGameDisplayName, getGameAliases, getArticleGameName } from './gameIdentity.js'

export const DETAIL_SOURCES = [
  ['dmNews', '3DM', '3dm', 'news'], ['dmReviews', '3DM', '3dm', 'review'],
  ['yxNews', '游侠', 'youxia', 'news'], ['yxReviews', '游侠', 'youxia', 'review'],
  ['gsNews', '游民', 'gamersky', 'news'], ['gsReviews', '游民', 'gamersky', 'review'],
  ['glNews', 'GameLook', 'gamelook', 'news'], ['grNews', '游资', 'gameres', 'news'],
  ['taptap', 'TapTap'], ['haoyou', '好游快爆'], ['jiuyou', '九游'], ['p16', '游资网'],
  ['hot', '官方动态'], ['weekly', '上周统计'], ['weeklyHistory', '历史统计'],
]

export function beijingDate(value) {
  const text = String(value || '').trim()
  if (!text) return ''
  const calendar = text.match(/^(\d{4})-(\d{2})-(\d{2})/)
  if (!calendar) return ''
  const day = new Date(`${calendar[0]}T12:00:00Z`)
  if (!Number.isFinite(day.getTime()) || day.toISOString().slice(0, 10) !== calendar[0]) return ''
  // Date-only and timezone-less collector strings are already Beijing local time.
  const local = text.match(/^(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2})(?::(\d{2})(?:\.\d+)?)?)?$/)
  if (local) {
    const parsed = new Date(`${local[1]}T${local[2] || '00:00'}:${local[3] || '00'}+08:00`)
    if (!Number.isFinite(parsed.getTime()) || new Date(parsed.getTime() + 8 * 3600000).toISOString().slice(0, 10) !== local[1]) return ''
    return `${local[1]}${local[2] ? ` ${local[2]}:${local[3] || '00'}` : ''}`
  }
  if (!/^\d{4}-\d{2}-\d{2}[T ].*(?:Z|[+-]\d{2}:?\d{2})$/i.test(text)) return ''
  const parsed = new Date(text.replace(' ', 'T'))
  if (!Number.isFinite(parsed.getTime())) return ''
  return new Date(parsed.getTime() + 8 * 3600000).toISOString().slice(0, 19).replace('T', ' ')
}

function currentDay() { return new Date(Date.now() + 8 * 3600000).toISOString().slice(0, 10) }
function unique(items, identify) {
  const seen = new Set()
  return items.filter((item) => { const id = identify(item); if (seen.has(id)) return false; seen.add(id); return true })
}
const sortDates = (a, b) => b.date.localeCompare(a.date) || (a.title || '').localeCompare(b.title || '')
const itemId = (item) => item.url || JSON.stringify([item.source, item.date, item.title])

export function buildGameIndex(data = {}, errors = {}, options = {}) {
  const index = new Map()
  const today = options.today || currentDay()
  const states = DETAIL_SOURCES.map(([key, label, source = key, type]) => ({
    key, source, sourceLabel: label, label: `${label}${type === 'news' ? '新闻' : type === 'review' ? '评测' : ''}`,
    crawledAt: beijingDate(Array.isArray(data[key]) ? data[key].map((row) => row.crawled_at || '').sort().at(-1) || '' : data[key]?.crawled_at || data[key]?.updated_at || data[key]?.generated_at || ''),
    status: errors[key] ? 'error' : data[key] != null ? 'ok' : 'missing', error: errors[key] || '',
  }))
  function game(name) {
    const key = resolveGameKey(name)
    if (!key) return null
    if (!index.has(key)) index.set(key, {
      key, name: getGameAliases(key).length ? getGameDisplayName(key) : normalizeGameName(name),
      aliases: getGameAliases(key), profiles: [], links: [], articles: [], officialUpdates: [], schedules: [],
      history: { latestWeekly: null, peakWeekly: null, cumulativeNews: null }, sourceStates: states,
      _weekly: [], _peak: [], _news: [], _officialStates: [],
    })
    const detail = index.get(key)
    const alias = normalizeGameName(name)
    if (alias !== detail.name && !detail.aliases.includes(alias)) detail.aliases.push(alias)
    return detail
  }
  function profile(detail, row, source, sourceLabel) {
    detail.profiles.push({ ...row, source, sourceLabel, platforms: row.platforms || (row.platform ? [row.platform] : []) })
    for (const [type, url] of [['official', row.official_url], ['source', row.source_url || row.detail_url]]) {
      if (url) detail.links.push({ source, sourceLabel, label: type === 'official' ? '官网' : `${sourceLabel}详情`, type, url })
    }
  }
  for (const [key, sourceLabel, source, type] of DETAIL_SOURCES.filter((entry) => entry[3])) {
    if (errors[key]) continue
    for (const row of data[key]?.items || []) {
      const detail = game(getArticleGameName(row))
      const date = beijingDate(row.published_at || row.date)
      if (!detail || !date || date.slice(0, 10) > today) continue
      detail.articles.push({ ...row, source, sourceLabel, type, date, summary: row.summary || '', url: row.url || '' })
    }
  }
  for (const [key, sourceLabel] of DETAIL_SOURCES.filter(([key]) => ['taptap', 'haoyou', 'jiuyou', 'p16'].includes(key))) {
    if (errors[key]) continue
    const rows = key === 'taptap' ? (data[key] || []).map((row) => [row, '']) : (data[key]?.days || []).flatMap((day) => (day.games || []).map((row) => [row, day.date]))
    for (const [row, dayDate] of rows) {
      const detail = game(row.game_name)
      if (!detail) continue
      profile(detail, row, key, sourceLabel)
      const date = beijingDate(row.release_date || row.event_date || row.date || dayDate)
      if (!date) continue
      detail.schedules.push({ date: date.slice(0, 10), type: row.event_type || row.status_tag || row.event_desc || '上线 / 测试', sources: [{ source: key, sourceLabel, url: row.source_url || row.detail_url || '', event_desc: row.event_desc || '' }] })
    }
  }
  if (!errors.hot) for (const publisher of data.hot?.publishers || []) for (const row of publisher.games || []) {
    const detail = game(row.game_name)
    if (!detail) continue
    profile(detail, { ...row, publisher: row.publisher || publisher.label }, 'official', '官方')
    const failed = row.source_status && row.source_status !== 'ok'
    detail._officialStates.push({ key: `official:${row.game_name}`, source: 'official', sourceLabel: '官方', label: `${row.game_name}官方`, crawledAt: beijingDate(row.crawled_at || data.hot.crawled_at || ''), status: failed ? 'error' : 'ok', error: failed ? row.source_error || row.error || `采集状态：${row.source_status}` : '' })
    if (failed) continue
    for (const update of row.updates || []) {
      const date = beijingDate(update.date || update.published_at)
      if (date && date.slice(0, 10) <= today) detail.officialUpdates.push({ ...update, source: 'official', sourceLabel: row.publisher || publisher.label || '官方', date, summary: update.summary || '', url: update.url || '' })
    }
  }
  if (!errors.weekly) for (const row of data.weekly?.hot_ranking || []) game(row.name)?._weekly.push({ ...row, week_start: row.week_start || data.weekly.week_start, week_end: row.week_end || data.weekly.week_end })
  if (!errors.weeklyHistory) {
    for (const row of data.weeklyHistory?.heat_ranking || []) game(row.name)?._peak.push({ ...row })
    // Full news_history is the ledger; news_ranking is only a truncated presentation.
    for (const row of data.weeklyHistory?.news_history || []) game(row.name)?._news.push({ ...row })
  }
  for (const detail of index.values()) {
    detail.articles = unique(detail.articles, itemId).sort(sortDates)
    detail.officialUpdates = unique(detail.officialUpdates, itemId).sort(sortDates)
    detail.profiles = unique(detail.profiles, (row) => JSON.stringify([row.source, row.publisher, row.categories, row.score, row.reservation_count, row.source_url, row.detail_url]))
    detail.links = unique(detail.links, (row) => row.url)
    const schedules = new Map()
    for (const row of detail.schedules) {
      const key = JSON.stringify([row.date, row.type])
      if (!schedules.has(key)) schedules.set(key, { ...row, sources: [] })
      schedules.get(key).sources.push(...row.sources)
    }
    detail.schedules = [...schedules.values()].map((row) => ({ ...row, sources: unique(row.sources, (source) => JSON.stringify([source.source, source.url])) })).sort(sortDates)
    detail._weekly.sort((a, b) => Number(b.heat_score) - Number(a.heat_score))
    detail._peak.sort((a, b) => Number(b.heat_score) - Number(a.heat_score) || (a.week_start || '').localeCompare(b.week_start || ''))
    detail.history.latestWeekly = detail._weekly.length ? { ...detail._weekly[0], records: detail._weekly } : null
    detail.history.peakWeekly = detail._peak.length ? { ...detail._peak[0], records: detail._peak } : null
    if (detail._news.length) {
      const records = detail._news
      const completeIds = records.every((row) => Array.isArray(row.article_ids) && row.article_ids.every((id) => typeof id === 'string' && id.length) && row.article_ids.length === Number(row.media_count))
      const merged = records.length === 1 || completeIds
      const first = records.map((row) => row.first_article_date).filter(Boolean).sort()[0] || ''
      const last = records.map((row) => row.last_article_date).filter(Boolean).sort().at(-1) || ''
      detail.history.cumulativeNews = { media_count: records.length === 1 ? records[0].media_count : completeIds ? new Set(records.flatMap((row) => row.article_ids)).size : null, first_article_date: first, last_article_date: last, records, separateRecords: !merged }
    }
    detail.sourceStates = [...states, ...detail._officialStates]
    delete detail._weekly; delete detail._peak; delete detail._news; delete detail._officialStates
  }
  return index
}

export function getGameDetail(index, gameKey) { return index?.get(resolveGameKey(gameKey)) || null }
