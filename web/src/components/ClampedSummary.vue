<script setup>
import { ref, watch, nextTick, onMounted, onUnmounted } from 'vue'
const props = defineProps({ text: { type: String, default: '' } })
const paragraph = ref(null)
const visibleText = ref(props.text)
let observer
let lastWidth = 0
function measure() {
  const element = paragraph.value
  if (!element || !element.clientWidth) return
  lastWidth = element.clientWidth
  const probe = element.cloneNode(false)
  Object.assign(probe.style, { position: 'fixed', visibility: 'hidden', pointerEvents: 'none', left: '-10000px', top: '0', width: `${lastWidth}px`, margin: '0' })
  probe.setAttribute('aria-hidden', 'true')
  document.body.appendChild(probe)
  try {
    const maxHeight = parseFloat(getComputedStyle(element).lineHeight) * 2 + 0.5
    probe.textContent = props.text
    if (probe.getBoundingClientRect().height <= maxHeight) { visibleText.value = props.text; return }
    const characters = Array.from(props.text)
    let lower = 0
    let upper = characters.length
    while (lower < upper) {
      const middle = Math.ceil((lower + upper) / 2)
      probe.textContent = characters.slice(0, middle).join('') + '……'
      if (probe.getBoundingClientRect().height <= maxHeight) lower = middle
      else upper = middle - 1
    }
    visibleText.value = characters.slice(0, lower).join('') + '……'
  } finally { probe.remove() }
}
watch(() => props.text, () => nextTick(measure))
onMounted(() => {
  measure()
  observer = new ResizeObserver(() => { if (paragraph.value?.clientWidth !== lastWidth) measure() })
  observer.observe(paragraph.value)
})
onUnmounted(() => observer?.disconnect())
</script>
<template><p ref="paragraph" class="clamped-summary">{{ visibleText }}</p></template>
<style scoped>
.clamped-summary { color: var(--text-2); font-size: 13px; line-height: 1.6; overflow-wrap: anywhere; }
</style>
