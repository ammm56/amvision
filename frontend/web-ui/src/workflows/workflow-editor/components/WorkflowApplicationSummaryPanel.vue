<template>
  <section class="workflow-graph-inspector-card workflow-graph-application-summary">
    <span class="workflow-graph-inspector-card__summary">
      <strong>{{ applicationId }}</strong>
      <small>
        {{ t('workflowEditor.editor.applicationInputs') }} {{ templateInputText || emptyText }}
        · {{ t('workflowEditor.editor.applicationOutputs') }} {{ templateOutputText || emptyText }}
      </small>
    </span>
    <small v-if="previewRunText" class="workflow-graph-application-summary__run">{{ previewRunText }}</small>
  </section>
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
