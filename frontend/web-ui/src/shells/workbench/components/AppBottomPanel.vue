<template>
  <footer class="app-bottom-panel">
    <div class="app-bottom-panel__left">
      <Activity :size="15" />
      <span>{{ projectStore.selectedProjectId }}</span>
      <span>{{ appStore.lastGlobalError || t('common.ready') }}</span>
    </div>
    <div class="app-bottom-panel__right">
      <ConnectionStatus />
      <span class="credential-pill">
        <ShieldCheck :size="15" />
        {{ sessionStore.credentialKind || t('common.none') }}
      </span>
    </div>
  </footer>
</template>

<script setup lang="ts">
import { Activity, ShieldCheck } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

import ConnectionStatus from './ConnectionStatus.vue'
import { useAppStore } from '@/app/stores/app.store'
import { useProjectStore } from '@/app/stores/project.store'
import { useSessionStore } from '@/app/stores/session.store'

const appStore = useAppStore()
const projectStore = useProjectStore()
const sessionStore = useSessionStore()
const { t } = useI18n()
</script>
