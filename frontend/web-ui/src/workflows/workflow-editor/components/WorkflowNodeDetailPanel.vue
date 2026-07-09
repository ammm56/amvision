<template>
  <div class="workflow-graph-inspector-body">
    <div class="workflow-graph-inspector-row">
      <span>节点</span>
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
      <span>分类</span>
      <strong>{{ node.definition?.category || 'unknown' }}</strong>
    </div>
    <div class="workflow-graph-inspector-row">
      <span>端口</span>
      <strong>{{ node.inputs.length }} in / {{ node.outputs.length }} out</strong>
    </div>
    <label class="workflow-graph-inspector-toggle-row">
      <span>
        <strong>启用节点</strong>
        <small>关闭后保存到图中，运行时跳过该节点。</small>
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
import type { WorkflowGraphNodeView } from '../nodes/useWorkflowGraphNodeViews'

defineProps<{
  node: WorkflowGraphNodeView
  readTitle: (node: WorkflowGraphNodeView) => string
}>()

const emit = defineEmits<{
  updateEnabled: [node: WorkflowGraphNodeView, event: Event]
}>()
</script>
