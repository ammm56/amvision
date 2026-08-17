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
          <StatusBadge tone="neutral">{{ previewRun.node_records.length }} records</StatusBadge>
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
      <div v-if="timingItems.length" class="workflow-graph-preview-result">
        <div class="workflow-graph-inspector-row">
          <span>{{ t('workflowEditor.editor.stageTimings') }}</span>
          <strong>{{ totalStageTiming }}</strong>
        </div>
        <div v-for="item in timingItems" :key="item.key" class="workflow-graph-inspector-row">
          <span>{{ item.key }}</span>
          <strong>{{ item.value }}</strong>
        </div>
      </div>
      <div v-if="nodeTimingItems.length" class="workflow-graph-preview-result">
        <div class="workflow-graph-inspector-row">
          <span>{{ t('workflowEditor.editor.nodeTimings') }}</span>
          <strong>{{ nodeTimingItems.length }} records</strong>
        </div>
        <div v-for="item in nodeTimingItems" :key="item.key" class="workflow-graph-inspector-row">
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
        </div>
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
import { computed } from 'vue'
import { useTranslation } from '@/platform/i18n'

import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import type { WorkflowJsonObject, WorkflowPreviewRun } from '../types'

const { t } = useTranslation()

const props = defineProps<{
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

const timingKeys = [
  'request_parse_ms',
  'process_startup_ms',
  'graph_execute_ms',
  'event_persist_ms',
  'response_serialize_ms',
] as const

const timingItems = computed(() => {
  const rawTimings = props.previewRun.metadata.timings
  if (!rawTimings || typeof rawTimings !== 'object' || Array.isArray(rawTimings)) return []
  const timings = rawTimings as Record<string, unknown>
  return timingKeys.flatMap((key) => {
    const value = timings[key]
    return typeof value === 'number' && Number.isFinite(value)
      ? [{ key, numericValue: value, value: `${value.toFixed(3)} ms` }]
      : []
  })
})

const totalStageTiming = computed(() => {
  const total = timingItems.value.reduce((sum, item) => sum + item.numericValue, 0)
  return `${total.toFixed(3)} ms`
})

const nodeTimingItems = computed(() => props.previewRun.node_records.flatMap((record, index) => {
  const duration = record.duration_ms
  if (typeof duration !== 'number' || !Number.isFinite(duration)) return []
  const nodeId = typeof record.node_id === 'string' && record.node_id ? record.node_id : 'unknown-node'
  const nodeTypeId = typeof record.node_type_id === 'string' && record.node_type_id ? record.node_type_id : ''
  return [{
    key: `${index}:${nodeId}`,
    label: `#${index + 1} ${nodeId}${nodeTypeId ? ` · ${nodeTypeId}` : ''}`,
    value: `${duration.toFixed(3)} ms`,
  }]
}))

const emit = defineEmits<{
  'open-json': [title: string, value: unknown, statusText: string | null]
}>()
</script>
