<template>
  <section class="workflow-graph-inspector-card workflow-graph-edge-summary">
    <span class="workflow-graph-edge-summary__endpoint">
      <small>Source</small>
      <strong>{{ endpoint('source') }}</strong>
      <small>{{ edge.source_node_id }} · {{ edge.source_port }}</small>
    </span>
    <span class="workflow-graph-edge-summary__arrow" aria-hidden="true">→</span>
    <span class="workflow-graph-edge-summary__endpoint">
      <small>Target</small>
      <strong>{{ endpoint('target') }}</strong>
      <small>{{ edge.target_node_id }} · {{ edge.target_port }}</small>
    </span>
    <Button variant="danger" @click="emit('delete-edge')">
      <Trash2 :size="16" />
      {{ t('workflowEditor.editor.deleteEdge') }}
    </Button>
  </section>
</template>

<script setup lang="ts">
import { Trash2 } from '@lucide/vue'
import { useTranslation } from '@/platform/i18n'

import Button from '@/shared/ui/components/Button.vue'
import type { WorkflowGraphEdge } from '../types'
import type { WorkflowGraphNodeView } from '../nodes/useWorkflowGraphNodeViews'

const { t } = useTranslation()

const props = defineProps<{
  edge: WorkflowGraphEdge
  nodes?: WorkflowGraphNodeView[]
}>()

/** 显示标题与端口名称；技术标识另列，连线序列化保持不变。 */
function endpoint(direction: 'source' | 'target'): string {
  const id = props.edge[`${direction}_node_id`]
  const portName = props.edge[`${direction}_port`]
  const node = props.nodes?.find(item => item.node.node_id === id)
  const port = (direction === 'source' ? node?.outputs : node?.inputs)?.find(item => item.name === portName)
  return `${node?.node.parameters.title || node?.title || id} · ${port?.display_name || portName}`
}

const emit = defineEmits<{
  'delete-edge': []
}>()
</script>
