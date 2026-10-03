import { ref, provide, nextTick, onMounted, onUnmounted } from 'vue'

export function useGameDetailNavigation({ activeSection, sectionKeys, defaultSection = 'weekly' }) {
  const gameKey = ref(new URLSearchParams(window.location.search).get('game') || '')
  let returnFocus = null
  let returnScroll = 0
  function gameHref(key) {
    const url = new URL(window.location.href)
    url.searchParams.set('section', activeSection.value)
    url.searchParams.set('game', key)
    return url.href
  }
  function openGame(key, event) {
    returnFocus = event?.currentTarget || document.activeElement
    returnScroll = window.scrollY
    const state = { ...window.history.state, gameDetailReturn: { url: window.location.href, scroll: returnScroll } }
    window.history.replaceState({ ...window.history.state, gameListScroll: returnScroll }, '', window.location.href)
    window.history.pushState(state, '', gameHref(key))
    gameKey.value = key
    nextTick(() => { window.scrollTo(0, 0); document.querySelector('[data-game-detail-heading]')?.focus({ preventScroll: true }) })
  }
  function restoreList(scroll = returnScroll) {
    nextTick(() => { window.scrollTo(0, scroll); if (returnFocus?.isConnected) returnFocus.focus({ preventScroll: true }) })
  }
  function syncUrl() {
    const query = new URLSearchParams(window.location.search)
    const section = query.get('section')
    activeSection.value = sectionKeys.includes(section) ? section : defaultSection
    gameKey.value = query.get('game') || ''
    if (!gameKey.value) restoreList(window.history.state?.gameListScroll ?? returnScroll)
    else nextTick(() => window.scrollTo(0, 0))
  }
  function closeDetail() {
    if (window.history.state?.gameDetailReturn) { window.history.back(); return }
    const url = new URL(window.location.href)
    url.searchParams.delete('game')
    const section = url.searchParams.get('section')
    activeSection.value = sectionKeys.includes(section) ? section : defaultSection
    url.searchParams.set('section', activeSection.value)
    window.history.replaceState({ ...window.history.state, gameDetailReturn: null }, '', url)
    gameKey.value = ''
    restoreList(0)
  }
  function exitDetail() {
    if (!gameKey.value) return
    const url = new URL(window.location.href)
    url.searchParams.delete('game')
    window.history.replaceState({ ...window.history.state, gameDetailReturn: null }, '', url)
    gameKey.value = ''
  }
  provide('game-detail-navigation', { gameHref, openGame })
  onMounted(() => window.addEventListener('popstate', syncUrl))
  onUnmounted(() => window.removeEventListener('popstate', syncUrl))
  return { gameKey, gameHref, openGame, closeDetail, exitDetail }
}
