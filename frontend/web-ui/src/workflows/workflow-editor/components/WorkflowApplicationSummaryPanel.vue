<template>
  <div class="workflow-graph-inspector-body">
    <div class="workflow-graph-inspector-row">
      <span>{{ t('workflowEditor.editor.application') }}</span>
      <strong>{{ applicationId }}</strong>
    </div>
    <div class="workflow-graph-inspector-row">
      <span>{{ t('workflowEditor.editor.applicationInputs') }}</span>
      <strong>{{ templateInputText || emptyText }}</strong>
    </div>
    <div class="workflow-graph-inspector-row">
      <span>{{ t('workflowEditor.editor.applicationOutputs') }}</span>
      <strong>{{ templateOutputText || emptyText }}</strong>
    </div>
    <div v-if="previewRunText" class="workflow-graph-inspector-row">
      <span>Preview run</span>
      <strong>{{ previewRunText }}</strong>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'

defineProps<{
  applicationId: string
  templateInputText: string
  templateOutputText: string
  emptyText: string
  previewRunText: string | null
}>()

const { t } = useI18n()
</script>
