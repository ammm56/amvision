<template>
  <section class="workflow-graph-inspector-card workflow-graph-edge-summary">
    <span class="workflow-graph-edge-summary__endpoint">
      <small>Source</small>
      <strong>{{ edge.source_node_id }} · {{ edge.source_port }}</strong>
    </span>
    <span class="workflow-graph-edge-summary__arrow" aria-hidden="true">→</span>
    <span class="workflow-graph-edge-summary__endpoint">
      <small>Target</small>
      <strong>{{ edge.target_node_id }} · {{ edge.target_port }}</strong>
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

const { t } = useTranslation()

defineProps<{
  edge: WorkflowGraphEdge
}>()

const emit = defineEmits<{
  'delete-edge': []
}>()
</script>
