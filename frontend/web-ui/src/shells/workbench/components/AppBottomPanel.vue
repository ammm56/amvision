<script setup lang="ts">
import { Activity } from '@lucide/vue'

import { useAppStore } from '@/app/stores/app.store'
import { useProjectStore } from '@/app/stores/project.store'

const appStore = useAppStore()
const projectStore = useProjectStore()
</script>

<template>
  <footer class="app-bottom-panel">
    <Activity :size="15" />
    <span>{{ projectStore.selectedProjectId }}</span>
    <span>{{ appStore.lastGlobalError || 'ready' }}</span>
  </footer>
</template>