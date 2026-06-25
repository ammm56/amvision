<template>
  <header class="workflow-graph-toolbar">
    <div class="workflow-graph-toolbar__title">
      <RouterLink to="/workflows/apps" class="workflow-graph-toolbar__back">
        <ArrowLeft :size="16" />
        {{ t('workflowEditor.actions.backToApps') }}
      </RouterLink>
      <div>
        <h1>{{ editorTitle }}</h1>
      </div>
    </div>
    <div class="workflow-graph-toolbar__meta">
      <span>{{ t('workflowEditor.fields.nodeCount') }} {{ nodeCount }}</span>
      <span>{{ t('workflowEditor.fields.edgeCount') }} {{ edgeCount }}</span>
      <span v-if="runtimeState">{{ runtimeState }}</span>
      <StatusBadge v-if="previewRunLabel" :tone="previewRunTone">{{ previewRunLabel }}</StatusBadge>
      <span v-if="statusMessage">{{ statusMessage }}</span>
    </div>
    <div class="workflow-graph-toolbar__actions">
      <Button variant="secondary" :disabled="loading" @click="emit('refresh')">
        <RefreshCw :size="16" />
        {{ t('common.refresh') }}
      </Button>
      <Button variant="secondary" @click="emit('toggleTheme')">
        <Sun v-if="graphTheme === 'dark'" :size="16" />
        <Moon v-else :size="16" />
        {{ graphTheme === 'dark' ? t('preferences.light') : t('preferences.dark') }}
      </Button>
      <Button variant="secondary" :disabled="previewDisabled" @click="emit('preview')">
        <Play :size="16" />
        {{ t('workflowEditor.actions.previewRun') }}
      </Button>
      <Button variant="primary" :disabled="saveDisabled" @click="emit('save')">
        <Save :size="16" />
        {{ t('workflowEditor.actions.saveWorkflowApp') }}
      </Button>
    </div>
  </header>
</template>

<script setup lang="ts">
import { ArrowLeft, Moon, Play, RefreshCw, Save, Sun } from '@lucide/vue'
import { RouterLink } from 'vue-router'
import { useI18n } from 'vue-i18n'

import Button from '@/shared/ui/components/Button.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'

defineProps<{
  editorTitle: string
  nodeCount: number
  edgeCount: number
  runtimeState: string | null
  previewRunLabel: string | null
  previewRunTone: 'neutral' | 'success' | 'warning' | 'danger' | 'info'
  statusMessage: string | null
  loading: boolean
  graphTheme: string
  previewDisabled: boolean
  saveDisabled: boolean
}>()

const emit = defineEmits<{
  refresh: []
  toggleTheme: []
  preview: []
  save: []
}>()

const { t } = useI18n()
</script>
