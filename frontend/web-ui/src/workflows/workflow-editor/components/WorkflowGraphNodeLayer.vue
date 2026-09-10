<template>
  <WorkflowGraphNode
    v-for="node in nodes"
    :key="node.node.node_id"
    v-bind="nodeProps"
    :node="node"
    @startNodeDrag="(event, node) => emit('startNodeDrag', event, node)"
    @nodeClick="(nodeId) => emit('nodeClick', nodeId)"
    @openNodeContextMenu="(event, node) => emit('openNodeContextMenu', event, node)"
    @startPortConnection="(event, node, port, direction) => emit('startPortConnection', event, node, port, direction)"
    @selectPortEndpoint="(node, port, direction) => emit('selectPortEndpoint', node, port, direction)"
    @openPortContextMenu="(event, node, port, direction) => emit('openPortContextMenu', event, node, port, direction)"
    @updateEnumParameter="(node, field, value) => emit('updateEnumParameter', node, field, value)"
    @updateCheckboxParameter="(node, field, event) => emit('updateCheckboxParameter', node, field, event)"
    @updateNumberParameter="(node, field, event) => emit('updateNumberParameter', node, field, event)"
    @updateTextParameter="(node, field, event) => emit('updateTextParameter', node, field, event)"
    @updateValueParameter="(node, field, value) => emit('updateValueParameter', node, field, value)"
    @updateJsonParameterDraft="(node, field, event) => emit('updateJsonParameterDraft', node, field, event)"
    @commitJsonParameterDraft="(node, field, event) => emit('commitJsonParameterDraft', node, field, event)"
    @selectDeploymentInstance="(node) => emit('selectDeploymentInstance', node)"
    @openPreviewDisplay="(display) => emit('openPreviewDisplay', display)"
    @openPreviewImage="(image) => emit('openPreviewImage', image)"
  />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import WorkflowGraphNode from './WorkflowGraphNode.vue'
import type { WorkflowGraphNodeView } from '../nodes/useWorkflowGraphNodeViews'
import type { WorkflowGraphNodeProps, WorkflowGraphNodeEvents } from './workflow-graph-node.types'

const props = defineProps<Omit<WorkflowGraphNodeProps, 'node'> & { nodes: WorkflowGraphNodeView[] }>()
const emit = defineEmits<WorkflowGraphNodeEvents>()
const nodeProps = computed(() => { const { nodes: _nodes, ...rest } = props; return rest })
</script>
