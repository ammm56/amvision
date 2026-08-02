<template>
  <section class="workflow-graph-inspector-card workflow-graph-node-summary">
    <div class="workflow-graph-inspector-card__header">
      <span class="workflow-graph-inspector-card__summary">
        <strong>{{ readTitle(node) }}</strong>
        <small :title="node.node.node_type_id">
          {{ node.node.node_type_id }} · {{ node.definition?.category || 'unknown' }}
        </small>
      </span>
      <label
        class="workflow-graph-inspector-switch"
        :title="t('workflowEditor.editor.enableNode')"
      >
        <WorkflowGraphCheckbox
          :aria-label="t('workflowEditor.editor.enableNode')"
          :checked="node.node.enabled !== false"
          @change="emit('updateEnabled', node, $event)"
        />
      </label>
    </div>
  </section>
</template>

<script setup lang="ts">
import { useTranslation } from '@/platform/i18n'

import type { WorkflowGraphNodeView } from '../nodes/useWorkflowGraphNodeViews'
import WorkflowGraphCheckbox from './WorkflowGraphCheckbox.vue'

const { t } = useTranslation()

defineProps<{
  node: WorkflowGraphNodeView
  readTitle: (node: WorkflowGraphNodeView) => string
}>()

const emit = defineEmits<{
  updateEnabled: [node: WorkflowGraphNodeView, event: Event]
}>()
</script>
