import test from 'node:test'
import assert from 'node:assert/strict'
import { createRenderer, ref, nextTick } from 'vue'
import { useGameDetailNavigation } from './useGameDetailNavigation.js'

const renderer = createRenderer({
  createComment: () => ({}), insert() {}, remove() {}, setElementText() {},
  createElement: () => ({}), createText: () => ({}), setText() {},
  parentNode: () => null, nextSibling: () => null, patchProp() {},
})
function setup(url = 'https://example.test/competitor-dashboard/?section=new-games&q=原神') {
  const listeners = new Map()
  const entries = [{ url, state: { preserved: true } }]
  let position = 0
  const scrolls = []
  const location = { href: url, search: new URL(url).search }
  function update(value) { location.href = String(value); location.search = new URL(value).search }
  function move(offset) {
    position += offset
    update(entries[position].url)
    listeners.get('popstate')?.()
  }
  globalThis.window = {
    location, scrollY: 734, scrollTo: (x, y) => scrolls.push(y),
    addEventListener: (name, fn) => listeners.set(name, fn),
    removeEventListener: (name) => listeners.delete(name),
    history: {
      get state() { return entries[position].state },
      replaceState(state, _, value) { entries[position] = { state, url: String(value) }; update(value) },
      pushState(state, _, value) { entries.splice(position + 1); entries.push({ state, url: String(value) }); position++; update(value) },
      back() { move(-1) }, forward() { move(1) },
    },
  }
  const focus = []
  const trigger = { isConnected: true, focus: (options) => focus.push(options) }
  globalThis.document = { activeElement: trigger, querySelector: () => ({ focus() {} }) }
  const activeSection = ref('new-games')
  let nav
  const app = renderer.createApp({ setup() {
    nav = useGameDetailNavigation({ activeSection, sectionKeys: ['weekly', 'new-games', 'news'] })
    return () => null
  } })
  app.mount({})
  return { nav, app, entries, listeners, scrolls, focus, trigger, activeSection }
}

test('detail URL preserves filters and round-trips Chinese, slash, ampersand', async () => {
  const s = setup()
  try {
    s.nav.openGame('游戏 / A&B', { currentTarget: s.trigger })
    await nextTick()
    const query = new URL(window.location.href).searchParams
    assert.equal(query.get('game'), '游戏 / A&B')
    assert.equal(query.get('section'), 'new-games')
    assert.equal(query.get('q'), '原神')
    assert.equal(s.entries.length, 2)
    assert.equal(window.history.state.preserved, true)
    assert.equal(window.history.state.gameDetailReturn.scroll, 734)
    assert.equal(s.scrolls.at(-1), 0)
  } finally { s.app.unmount() }
})

test('browser back and forward restore detail, list scroll, trigger focus, state', async () => {
  const s = setup()
  try {
    s.nav.openGame('genshin-impact', { currentTarget: s.trigger })
    await nextTick()
    window.history.replaceState({ ...window.history.state, filterUpdated: true }, '', window.location.href)
    s.nav.closeDetail()
    await nextTick()
    assert.equal(s.nav.gameKey.value, '')
    assert.equal(s.scrolls.at(-1), 734)
    assert.deepEqual(s.focus.at(-1), { preventScroll: true })
    window.history.forward()
    await nextTick()
    assert.equal(s.nav.gameKey.value, 'genshin-impact')
    assert.equal(window.history.state.filterUpdated, true)
    assert.equal(s.scrolls.at(-1), 0)
  } finally { s.app.unmount() }
  assert.equal(s.listeners.has('popstate'), false)
})

test('direct detail returns to requested valid section, invalid section returns weekly', async () => {
  for (const [section, expected] of [['news', 'news'], ['invalid', 'weekly'], ['', 'weekly']]) {
    const s = setup(`https://example.test/competitor-dashboard/?section=${section}&game=unknown`)
    try {
      assert.equal(s.nav.gameKey.value, 'unknown')
      s.nav.closeDetail()
      await nextTick()
      assert.equal(s.activeSection.value, expected)
      assert.equal(new URL(window.location.href).searchParams.has('game'), false)
      assert.equal(s.entries.length, 1)
      assert.equal(s.scrolls.at(-1), 0)
    } finally { s.app.unmount() }
  }
})

test('section switch exits detail and clears game and return metadata', async () => {
  const s = setup()
  try {
    s.nav.openGame('genshin-impact', { currentTarget: s.trigger })
    s.nav.exitDetail()
    assert.equal(s.nav.gameKey.value, '')
    assert.equal(new URL(window.location.href).searchParams.has('game'), false)
    assert.equal(window.history.state.gameDetailReturn, null)
    assert.equal(window.history.state.preserved, true)
    await nextTick()
  } finally { s.app.unmount() }
})
