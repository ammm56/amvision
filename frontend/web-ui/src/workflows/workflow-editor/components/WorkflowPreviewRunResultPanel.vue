<template>
  <div class="workflow-graph-preview-inputs">
    <div class="workflow-graph-panel__header">
      <h2>运行结果</h2>
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
          <span>失败消息</span>
          <strong>{{ failureMessage }}</strong>
        </div>
        <div v-if="failureNodeLabel" class="workflow-graph-inspector-row">
          <span>失败节点</span>
          <strong>{{ failureNodeLabel }}</strong>
        </div>
        <div v-if="failureLocation" class="workflow-graph-inspector-row">
          <span>执行位置</span>
          <strong>{{ failureLocation }}</strong>
        </div>
        <div v-if="failureDetailMessage && failureDetailMessage !== failureMessage" class="workflow-graph-inspector-row">
          <span>底层错误</span>
          <strong>{{ failureDetailMessage }}</strong>
        </div>
        <pre
          v-if="failureDetailsJson"
          class="json-view"
          @dblclick.stop="emit('open-json', '失败详情', failureDetails, failureDetailMessage || failureMessage)"
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
        {{ hasNodeDisplays ? '本次 Preview 没有 http_response 输出，结果已在节点预览中显示。' : '本次 Preview 没有 http_response 输出。' }}
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import type { WorkflowJsonObject, WorkflowPreviewRun } from '../types'

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
