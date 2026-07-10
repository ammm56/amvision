<template>
  <header class="workflow-graph-toolbar">
    <div class="workflow-graph-toolbar__title">
      <RouterLink to="/workflows/apps" class="workflow-graph-toolbar__back">
        <ArrowLeft :size="16" />
        {{ t('workflowEditor.actions.backToApps') }}
      </RouterLink>
      <div class="workflow-graph-toolbar__title-main">
        <div v-if="titleEditing" class="workflow-graph-toolbar__title-editor">
          <input
            ref="titleInputRef"
            :value="titleDraft"
            :disabled="titleSaving"
            @input="emit('updateTitleDraft', readInputValue($event))"
            @keydown.enter.prevent="emit('commitTitle')"
            @keydown.esc.prevent="emit('cancelTitle')"
          />
          <button
            type="button"
            :title="t('workflowEditor.actions.saveAppName')"
            :aria-label="t('workflowEditor.actions.saveAppName')"
            :disabled="titleSaving || !titleDraft.trim()"
            @mousedown.prevent
            @click="emit('commitTitle')"
          >
            <Check :size="14" />
          </button>
          <button
            type="button"
            :title="t('workflowEditor.actions.cancelAppNameEdit')"
            :aria-label="t('workflowEditor.actions.cancelAppNameEdit')"
            :disabled="titleSaving"
            @mousedown.prevent
            @click="emit('cancelTitle')"
          >
            <X :size="14" />
          </button>
        </div>
        <div v-else class="workflow-graph-toolbar__title-view">
          <h1
            :title="titleEditable ? t('workflowEditor.actions.renameWorkflowApp') : editorTitle"
            @dblclick="titleEditable && emit('beginTitleEdit')"
          >
            {{ editorTitle }}
          </h1>
          <button
            v-if="titleEditable"
            type="button"
            class="workflow-graph-toolbar__title-edit"
            :title="t('workflowEditor.actions.renameWorkflowApp')"
            :aria-label="t('workflowEditor.actions.renameWorkflowApp')"
            @click="emit('beginTitleEdit')"
          >
            <SquarePen :size="14" />
          </button>
        </div>
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
import { nextTick, ref, watch } from 'vue'
import { ArrowLeft, Check, Moon, Play, RefreshCw, Save, SquarePen, Sun, X } from '@lucide/vue'
import { RouterLink } from 'vue-router'
import { useI18n } from 'vue-i18n'

import Button from '@/shared/ui/components/Button.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'

const props = defineProps<{
  editorTitle: string
  titleDraft: string
  titleEditing: boolean
  titleSaving: boolean
  titleEditable: boolean
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
  beginTitleEdit: []
  updateTitleDraft: [value: string]
  commitTitle: []
  cancelTitle: []
  refresh: []
  toggleTheme: []
  preview: []
  save: []
}>()

const { t } = useI18n()
const titleInputRef = ref<HTMLInputElement | null>(null)

watch(
  () => props.titleEditing,
  async (editing) => {
    if (!editing) return
    await nextTick()
    titleInputRef.value?.focus()
    titleInputRef.value?.select()
  },
)

function readInputValue(event: Event): string {
  const target = event.target
  return target instanceof HTMLInputElement ? target.value : ''
}
</script>
