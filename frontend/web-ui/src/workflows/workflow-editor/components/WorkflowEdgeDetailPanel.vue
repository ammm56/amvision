<template>
  <div class="workflow-graph-inspector-body">
    <div class="workflow-graph-inspector-row">
      <span>Edge</span>
      <strong>{{ edge.edge_id }}</strong>
    </div>
    <div class="workflow-graph-inspector-row">
      <span>Source</span>
      <strong>{{ edge.source_node_id }} / {{ edge.source_port }}</strong>
    </div>
    <div class="workflow-graph-inspector-row">
      <span>Target</span>
      <strong>{{ edge.target_node_id }} / {{ edge.target_port }}</strong>
    </div>
    <Button variant="danger" @click="emit('delete-edge')">
      <Trash2 :size="16" />
      删除连线
    </Button>
  </div>
</template>

<script setup lang="ts">
import { Trash2 } from '@lucide/vue'

import Button from '@/shared/ui/components/Button.vue'
import type { WorkflowGraphEdge } from '../types'

defineProps<{
  edge: WorkflowGraphEdge
}>()

const emit = defineEmits<{
  'delete-edge': []
}>()
</script>
