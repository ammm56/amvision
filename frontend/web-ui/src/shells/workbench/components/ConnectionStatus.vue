<script setup lang="ts">
import { computed } from 'vue'
import { Circle, WifiOff } from '@lucide/vue'

import { useAppStore } from '@/app/stores/app.store'

const appStore = useAppStore()

const label = computed(() => {
  if (appStore.backendConnectionState === 'online') return 'backend online'
  if (appStore.backendConnectionState === 'offline') return 'backend offline'
  if (appStore.backendConnectionState === 'degraded') return 'backend degraded'
  return 'checking backend'
})
</script>

<template>
  <span class="connection-status" :class="`connection-status--${appStore.backendConnectionState}`">
    <WifiOff v-if="appStore.backendConnectionState === 'offline'" :size="15" />
    <Circle v-else :size="12" />
    {{ label }}
  </span>
</template>