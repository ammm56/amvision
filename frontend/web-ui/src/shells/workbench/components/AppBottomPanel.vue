<script setup lang="ts">
import { Activity } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

import { useAppStore } from '@/app/stores/app.store'
import { useProjectStore } from '@/app/stores/project.store'

const appStore = useAppStore()
const projectStore = useProjectStore()
const { t } = useI18n()
</script>

<template>
  <footer class="app-bottom-panel">
    <Activity :size="15" />
    <span>{{ projectStore.selectedProjectId }}</span>
    <span>{{ appStore.lastGlobalError || t('common.ready') }}</span>
  </footer>
</template>