<template>
  <div class="workflow-graph-preview-inputs">
    <div class="workflow-graph-panel__header">
      <h2>{{ t('workflowEditor.editor.runResult') }}</h2>
      <StatusBadge :tone="badgeTone">
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
          <StatusBadge tone="info">{{ previewRun.node_records.length }} records</StatusBadge>
        </div>
      </div>
      <div v-if="previewRun.state === 'failed'" class="workflow-graph-preview-result workflow-graph-preview-result--error">
        <div class="workflow-graph-inspector-row">
          <span>{{ t('workflowEditor.editor.failureMessage') }}</span>
          <strong>{{ failureMessage }}</strong>
        </div>
        <div v-if="failureNodeLabel" class="workflow-graph-inspector-row">
          <span>{{ t('workflowEditor.editor.failureNode') }}</span>
          <strong>{{ failureNodeLabel }}</strong>
        </div>
        <div v-if="failureLocation" class="workflow-graph-inspector-row">
          <span>{{ t('workflowEditor.editor.executionLocation') }}</span>
          <strong>{{ failureLocation }}</strong>
        </div>
        <div v-if="failureDetailMessage && failureDetailMessage !== failureMessage" class="workflow-graph-inspector-row">
          <span>{{ t('workflowEditor.editor.underlyingError') }}</span>
          <strong>{{ failureDetailMessage }}</strong>
        </div>
        <pre
          v-if="failureDetailsJson"
          class="json-view"
          @dblclick.stop="emit('open-json', t('workflowEditor.editor.failureDetails'), failureDetails, failureDetailMessage || failureMessage)"
        >{{ failureDetailsJson }}</pre>
      </div>
      <div v-if="httpResponse" class="workflow-graph-preview-result">
        <div class="workflow-graph-inspector-row">
          <span>HTTP status</span>
          <strong>{{ httpStatus ?? 'unknown' }}</strong>
        </div>
        <pre
          class="json-view"
          @dblclick.stop="emit('open-json', 'HTTP Response', httpResponseBodyValue, `HTTP ${httpStatus ?? 'unknown'}`)"
        >{{ httpResponseBodyJson || httpResponseJson }}</pre>
      </div>
      <div v-else-if="previewRun.state !== 'failed'" class="workflow-graph-preview-card__empty">
        {{ hasNodeDisplays ? t('workflowEditor.editor.noHttpResponseWithNodePreview') : t('workflowEditor.editor.noHttpResponse') }}
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { useTranslation } from '@/platform/i18n'

import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import type { WorkflowJsonObject, WorkflowPreviewRun } from '../types'

const { t } = useTranslation()

defineProps<{
  previewRun: WorkflowPreviewRun
  badgeTone: 'info' | 'danger' | 'neutral'
  statusLabel: string
  createdAtText: string
  failureMessage: string
  failureNodeLabel: string
  failureLocation: string
  failureDetailMessage: string
  failureDetails: WorkflowJsonObject | null
  failureDetailsJson: string
  httpResponse: WorkflowJsonObject | null
  httpResponseBodyValue: unknown
  httpStatus: number | null
  httpResponseJson: string
  httpResponseBodyJson: string
  hasNodeDisplays: boolean
}>()

const emit = defineEmits<{
  'open-json': [title: string, value: unknown, statusText: string | null]
}>()
</script>
