<template>
  <div class="workflow-graph-new-app-panel">
    <div class="workflow-graph-panel__header workflow-graph-panel__header--compact">
      <div>
        <h2>首次保存</h2>
      </div>
      <StatusBadge :tone="saveBlocker ? 'warning' : 'success'">{{ saveBlocker ? '待完成' : '可保存' }}</StatusBadge>
    </div>
    <label class="workflow-graph-preview-field">
      <span>应用名称</span>
      <input :value="draft.displayName" placeholder="检测应用" @input="emit('update-display-name', $event)" />
    </label>
    <label class="workflow-graph-preview-field">
      <span>应用 id</span>
      <input :value="draft.applicationId" placeholder="inspection-app" @input="emit('update-application-id', $event)" @change="emit('normalize-application-id', $event)" />
    </label>
    <label class="workflow-graph-preview-field">
      <span>图 id</span>
      <input :value="draft.graphId" placeholder="inspection-graph" @input="emit('update-graph-id', $event)" @change="emit('normalize-graph-id', $event)" />
    </label>
    <label class="workflow-graph-preview-field">
      <span>图版本</span>
      <input :value="draft.graphVersion" placeholder="1.0.0" @input="emit('update-graph-version', $event)" @change="emit('normalize-graph-version', $event)" />
    </label>
    <label class="workflow-graph-preview-field">
      <span>说明</span>
      <input :value="draft.description" placeholder="可选" @input="emit('update-description', $event)" />
    </label>
    <p class="workflow-graph-preview-hint" :class="{ 'workflow-graph-preview-hint--danger': saveBlocker }">
      {{ saveBlocker || '首次保存会创建应用和图。' }}
    </p>
  </div>
</template>

<script setup lang="ts">
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
</script>
