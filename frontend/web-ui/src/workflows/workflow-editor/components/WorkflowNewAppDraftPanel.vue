<template>
  <div class="workflow-graph-new-app-panel">
    <div class="workflow-graph-panel__header workflow-graph-panel__header--compact">
      <div>
        <h2>{{ t('workflowEditor.editor.firstSave') }}</h2>
      </div>
      <StatusBadge :tone="saveBlocker ? 'warning' : 'success'">
        {{ saveBlocker ? t('workflowEditor.editor.incomplete') : t('workflowEditor.editor.canSave') }}
      </StatusBadge>
    </div>
    <label class="workflow-graph-preview-field">
      <span>{{ t('workflowEditor.editor.appName') }}</span>
      <input :value="draft.displayName" :placeholder="t('workflowEditor.editor.appNamePlaceholder')" @input="emit('update-display-name', $event)" />
    </label>
    <label class="workflow-graph-preview-field">
      <span>{{ t('workflowEditor.editor.appId') }}</span>
      <input :value="draft.applicationId" placeholder="inspection-app" @input="emit('update-application-id', $event)" @change="emit('normalize-application-id', $event)" />
    </label>
    <label class="workflow-graph-preview-field">
      <span>{{ t('workflowEditor.editor.graphId') }}</span>
      <input :value="draft.graphId" placeholder="inspection-graph" @input="emit('update-graph-id', $event)" @change="emit('normalize-graph-id', $event)" />
    </label>
    <label class="workflow-graph-preview-field">
      <span>{{ t('workflowEditor.editor.graphVersion') }}</span>
      <input :value="draft.graphVersion" placeholder="1.0.0" @input="emit('update-graph-version', $event)" @change="emit('normalize-graph-version', $event)" />
    </label>
    <label class="workflow-graph-preview-field">
      <span>{{ t('workflowEditor.editor.formDescription') }}</span>
      <input :value="draft.description" :placeholder="t('workflowEditor.editor.optional')" @input="emit('update-description', $event)" />
    </label>
    <p v-if="saveBlocker" class="workflow-graph-preview-hint workflow-graph-preview-hint--danger">
      {{ saveBlocker }}
    </p>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'

export interface WorkflowNewAppDraftView {
  applicationId: string
  displayName: string
  graphId: string
  graphVersion: string
  description: string
}

defineProps<{
  draft: WorkflowNewAppDraftView
  saveBlocker: string | null
}>()

const emit = defineEmits<{
  'update-display-name': [event: Event]
  'update-application-id': [event: Event]
  'update-graph-id': [event: Event]
  'update-graph-version': [event: Event]
  'update-description': [event: Event]
  'normalize-application-id': [event: Event]
  'normalize-graph-id': [event: Event]
  'normalize-graph-version': [event: Event]
}>()

const { t } = useI18n()
</script>
