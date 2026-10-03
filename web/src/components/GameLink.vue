<script setup>
import { computed, inject } from 'vue'
import { resolveGameKey } from '../utils/gameIdentity.js'
const props = defineProps({ name: { type: String, default: '' } })
const navigation = inject('game-detail-navigation', null)
const key = computed(() => resolveGameKey(props.name))
const href = computed(() => navigation?.gameHref(key.value) || `?game=${encodeURIComponent(key.value)}`)
function click(event) {
  if (!navigation || event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.currentTarget.target === '_blank') return
  event.preventDefault()
  navigation.openGame(key.value, event)
}
</script>
<template>
  <a v-if="key" :href="href" @click="click"><slot>{{ name }}</slot></a>
  <span v-else><slot>{{ name || '未知游戏' }}</slot></span>
</template>
