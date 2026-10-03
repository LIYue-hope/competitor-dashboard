import test from 'node:test'
import assert from 'node:assert/strict'
import { normalizeGameName, resolveGameKey, createGameIdentity, getArticleGameName } from './gameIdentity.js'

test('normalization handles whitespace and Chinese colon without guessing aliases', () => {
  assert.equal(normalizeGameName('  龙之剑 : 觉醒  '), '龙之剑：觉醒')
  assert.equal(normalizeGameName('Fate/Grand Order & Friends'), 'Fate/Grand Order & Friends')
  assert.equal(normalizeGameName('A PLATiNA :: LAB'), 'A PLATiNA :: LAB')
  assert.equal(resolveGameKey(' GENSHIN   IMPACT '), resolveGameKey('原神'))
  assert.notEqual(resolveGameKey('原神'), resolveGameKey('原神2'))
  assert.equal(resolveGameKey('未知游戏'), '')
  assert.equal(resolveGameKey(''), '')
})

test('conflicting aliases fail including another game canonical key', () => {
  assert.throws(() => createGameIdentity({ games: [
    { key: 'one', name: '游戏甲', aliases: ['Shared'] },
    { key: 'two', name: '游戏乙', aliases: [' shared '] },
  ] }), /别名冲突/)
})

test('legacy reviews use an explicit bracketed title only', () => {
  assert.equal(getArticleGameName({ title: '《狂热运输3》评测' }), '狂热运输3')
  assert.equal(getArticleGameName({ title: '原神2评测' }), '')
})
