<template>
  <span class="connection-status" :class="`connection-status--${appStore.backendConnectionState}`">
    <WifiOff v-if="appStore.backendConnectionState === 'offline'" :size="15" />
    <Circle v-else :size="12" />
    {{ label }}
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Circle, WifiOff } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

import { useAppStore } from '@/app/stores/app.store'

const appStore = useAppStore()
const { t } = useI18n()

const label = computed(() => {
  if (appStore.backendConnectionState === 'online') return t('connection.online')
  if (appStore.backendConnectionState === 'offline') return t('connection.offline')
  if (appStore.backendConnectionState === 'degraded') return t('connection.degraded')
  return t('connection.checking')
})
</script>