<template>
  <div class="workflow-graph-inspector-body">
    <div class="workflow-graph-inspector-row">
      <span>{{ t('workflowEditor.editor.node') }}</span>
      <strong>{{ readTitle(node) }}</strong>
    </div>
    <div class="workflow-graph-inspector-row">
      <span>Node ID</span>
      <strong>{{ node.node.node_id }}</strong>
    </div>
    <div class="workflow-graph-inspector-row">
      <span>Node type</span>
      <strong>{{ node.node.node_type_id }}</strong>
    </div>
    <div class="workflow-graph-inspector-row">
      <span>{{ t('workflowEditor.editor.category') }}</span>
      <strong>{{ node.definition?.category || 'unknown' }}</strong>
    </div>
    <div class="workflow-graph-inspector-row">
      <span>{{ t('workflowEditor.editor.ports') }}</span>
      <strong>{{ node.inputs.length }} in / {{ node.outputs.length }} out</strong>
    </div>
    <label class="workflow-graph-inspector-toggle-row">
      <span>
        <strong>{{ t('workflowEditor.editor.enableNode') }}</strong>
        <small>{{ t('workflowEditor.editor.enableNodeHint') }}</small>
      </span>
      <input
        type="checkbox"
        :checked="node.node.enabled !== false"
        @change="emit('updateEnabled', node, $event)"
      />
    </label>
  </div>
</template>

<script setup lang="ts">
import { useTranslation } from '@/platform/i18n'

import type { WorkflowGraphNodeView } from '../nodes/useWorkflowGraphNodeViews'

const { t } = useTranslation()

defineProps<{
  node: WorkflowGraphNodeView
  readTitle: (node: WorkflowGraphNodeView) => string
}>()

const emit = defineEmits<{
  updateEnabled: [node: WorkflowGraphNodeView, event: Event]
}>()
</script>
