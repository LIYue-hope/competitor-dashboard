import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'

/**
 * 多级吸顶 Tab 栏的滚动行为，供新游监测 / 热门动态 / 游戏资讯三个板块共用。
 *
 * 做两件事：
 *   1. 向下滚过阈值给吸顶栏加 compact：多行折成一行，把垂直空间还给内容；
 *   2. 日期锚点做 scroll spy，高亮当前视口顶部所在的那一段。
 *
 * 折叠会让吸顶栏矮几十像素，而它是 in-flow 的 sticky 元素，高度一变整个文档就缩。
 * 慢速滚动之所以抖、短页面之所以滚不动，是两个反馈环：
 *   a. 浏览器 scroll anchoring 反向补偿 scrollTop
 *      （已在 style.css 里用 overflow-anchor: none 关掉）
 *   b. 文档变矮 → scrollY 被夹回 → 掉出阈值 → 展开 → 变高 → 又能滚 → 折叠…… 死循环
 *
 * b 的根治办法不是"短页面就别折叠"——那样中等长度的页面也会被误判成不能折。
 * 正确做法是折叠的同时给 body 补上等量的 padding-bottom，让文档总高度前后完全不变，
 * scrollY 就不会被夹，环也就断了。
 *
 * 补偿量必须实测：各板块行数与控件宽度不同，写死一个数一定有板块对不上。
 *
 * 三个板块用 v-show 共存于 DOM，所以所有逻辑都由 active 闸门控制——
 * 只有当前显示的板块才响应滚动、才拥有 body 补偿，否则多个实例会互相覆盖。
 */

const COMPACT_ON = 170 // 向下滚过这里才折叠
const COMPACT_OFF = 90 // 向上退回这里才展开；中间 80px 是死区，避免临界抖动
const SPY_LINE = 150 // scroll spy 判定线，约等于折叠后吸顶栏底边

export function useStickyTabs(stackRef, rootRef, activeRef) {
  const compact = ref(false)
  // 当前视口顶部所在的日期段 id，模板用它决定哪个日期 Tab 高亮
  const activeAnchor = ref('')

  let delta = 0
  let queued = false

  // 量一次展开态与折叠态的高度差。直接改 DOM class 再同步还原，
  // 全程无 await，Vue 不会在中间 patch，不会和 :class 绑定打架。
  function measure() {
    const el = stackRef.value
    if (!el) {
      delta = 0
      return
    }
    const was = el.classList.contains('compact')
    el.classList.remove('compact')
    const expanded = el.offsetHeight
    el.classList.add('compact')
    const collapsed = el.offsetHeight
    el.classList.toggle('compact', was)
    delta = Math.max(0, expanded - collapsed)
  }

  function setPad(on) {
    document.body.style.paddingBottom = on ? `${delta}px` : ''
  }

  function apply() {
    queued = false
    if (!activeRef.value) return

    const y = window.scrollY
    if (!compact.value && y > COMPACT_ON) {
      compact.value = true
      setPad(true)
    } else if (compact.value && y < COMPACT_OFF) {
      compact.value = false
      setPad(false)
    }

    const root = rootRef.value
    if (!root) return
    const heads = root.querySelectorAll('.date-head')
    if (!heads.length) return
    let current = heads[0].id
    for (const h of heads) {
      if (h.getBoundingClientRect().top <= SPY_LINE) current = h.id
    }
    activeAnchor.value = current
  }

  // 滚动事件高频触发，合并到下一帧统一读写，避免同一帧内反复强制重排
  function onScroll() {
    if (queued) return
    queued = true
    requestAnimationFrame(apply)
  }

  function onResize() {
    measure()
    onScroll()
  }

  /** 内容变化（切 Tab、刷新数据）后重新实测补偿量并复位 */
  async function remeasure() {
    compact.value = false
    setPad(false)
    await nextTick()
    measure()
    onScroll()
  }

  // 板块被切走时交还 body 补偿，避免隐藏的实例把补白留在页面上
  watch(activeRef, (on) => {
    if (on) remeasure()
    else {
      compact.value = false
      setPad(false)
    }
  })

  onMounted(() => {
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', onResize, { passive: true })
    if (activeRef.value) remeasure()
  })

  onUnmounted(() => {
    window.removeEventListener('scroll', onScroll)
    window.removeEventListener('resize', onResize)
    if (activeRef.value) setPad(false)
  })

  return { compact, activeAnchor, remeasure }
}

/** 点日期 Tab：平滑滚到对应段落。滚动位置的偏移由 .date-head 的 scroll-margin-top 决定。 */
export function jumpToAnchor(id) {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
