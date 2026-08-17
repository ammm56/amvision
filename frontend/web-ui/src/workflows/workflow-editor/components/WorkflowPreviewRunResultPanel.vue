<template>
  <div class="workflow-graph-preview-inputs">
    <div class="workflow-graph-panel__header">
      <h2>{{ t('workflowEditor.editor.runResult') }}</h2>
      <StatusBadge :tone="badgeTone" with-dot>
        {{ statusLabel }}
      </StatusBadge>
    </div>
    <section class="workflow-graph-preview-binding">
      <div class="workflow-graph-preview-binding__header">
        <span class="workflow-graph-preview-binding__summary">
          <strong>{{ previewRun.preview_run_id }}</strong>
          <small>{{ createdAtText }}</small>
        </span>
        <div class="workflow-graph-preview-binding__tools">
          <span class="workflow-graph-preview-run__record-count">
            {{ t('workflowEditor.editor.nodeRecordCount', { count: previewRun.node_records.length }) }}
          </span>
        </div>
      </div>
      <pre
        class="json-view workflow-graph-preview-result__raw-json"
        @dblclick.stop="emit('open-json', t('workflowEditor.editor.runResult'), previewRun, statusLabel)"
      >{{ rawJsonText }}</pre>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useTranslation } from '@/platform/i18n'

import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import type { WorkflowPreviewRun } from '../types'

const { t } = useTranslation()

const props = defineProps<{
  previewRun: WorkflowPreviewRun
  badgeTone: 'success' | 'danger' | 'neutral'
  statusLabel: string
  createdAtText: string
}>()
const rawJsonText = computed(() => JSON.stringify(props.previewRun, null, 2))

const emit = defineEmits<{
  'open-json': [title: string, value: unknown, statusText: string | null]
}>()
</script>
