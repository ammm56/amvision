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
  </div>
</template>

<script setup lang="ts">
import type { NodeDefinition, NodePortDefinition, WorkflowGraphNode } from '../types'

interface WorkflowNodeDetailNode {
  node: WorkflowGraphNode
  definition: NodeDefinition | null
  title: string
  x: number
  y: number
  width: number
  inputs: NodePortDefinition[]
  outputs: NodePortDefinition[]
}

defineProps<{
  node: WorkflowNodeDetailNode
  readTitle: (node: WorkflowNodeDetailNode) => string
}>()
</script>
