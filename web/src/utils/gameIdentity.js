import config from '../config/gameAliases.json' with { type: 'json' }

const placeholders = new Set(['未知游戏', '未知', '未命名', '暂无', 'unknown', 'unknown game', '-', '—'])

export function normalizeGameName(name) {
  if (typeof name !== 'string') return ''
  let normalized = name.trim().replace(/\s+/g, ' ')
  if (/[\u4e00-\u9fff\u3040-\u30ff]/u.test(normalized)) {
    normalized = normalized.replace(/(?<!:):(?!:)/g, '：').replace(/\s*：\s*/g, '：')
  }
  // Slashes can be part of a title. Only manually configured aliases merge games.
  return normalized
}

export function createGameIdentity(configuration) {
  const byName = new Map()
  const byKey = new Map()
  for (const game of configuration.games || []) {
    if (!game.key || !normalizeGameName(game.name) || byKey.has(game.key)) throw new Error(`游戏别名配置中的键无效或重复：${game.key}`)
    byKey.set(game.key, game)
    for (const alias of [game.key, game.name, ...(game.aliases || [])]) {
      const normalized = normalizeGameName(alias).toLowerCase()
      if (!normalized || placeholders.has(normalized)) throw new Error(`游戏别名无效：${alias}`)
      const previous = byName.get(normalized)
      if (previous && previous !== game.key) throw new Error(`游戏别名冲突：${alias} (${previous}, ${game.key})`)
      byName.set(normalized, game.key)
    }
  }
  return {
    resolveGameKey(name) {
      const normalized = normalizeGameName(name).toLowerCase()
      return !normalized || placeholders.has(normalized) ? '' : byName.get(normalized) || normalized
    },
    getGameDisplayName(key) { return byKey.get(key)?.name || normalizeGameName(key) },
    getGameAliases(key) { const game = byKey.get(key); return game ? [game.name, ...(game.aliases || [])] : [] },
  }
}

const identity = createGameIdentity(config)
export const resolveGameKey = identity.resolveGameKey
export const getGameDisplayName = identity.getGameDisplayName
export const getGameAliases = identity.getGameAliases

export function getArticleGameName(item) {
  if (normalizeGameName(item?.game_name)) return item.game_name
  const match = String(item?.title || '').match(/《([^《》]{1,40})》|【([^【】]{1,40})】/u)
  return match ? normalizeGameName(match[1] || match[2]) : ''
}
