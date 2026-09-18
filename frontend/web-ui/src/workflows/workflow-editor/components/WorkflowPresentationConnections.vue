<template>
  <section v-if="selected && ['core.io.image-preview', 'core.io.value-display'].includes(selected.node.node_type_id)" class="workflow-graph-inspector-card presentation-connections">
    <strong>{{ pt(selected.node.node_type_id === 'core.io.image-preview' ? 'presentation' : 'targets') }}</strong>
    <span v-if="!connections.length">{{ pt(selected.node.node_type_id === 'core.io.image-preview' ? 'imageOnly' : 'noTargets') }}</span>
    <button v-for="item in connections" :key="item.id" type="button" :title="pt('locate')" @click="emit('locate', item.id)">
      {{ item.title }}<small v-if="!item.enabled">{{ pt('disabled') }}</small>
    </button>
  </section>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { presentationMessages } from '../app-mode/presentation-messages'
import type { WorkflowGraphNodeView } from '../nodes/useWorkflowGraphNodeViews'
import type { WorkflowGraphEdge } from '../types'
const props = defineProps<{ selected: WorkflowGraphNodeView | null; nodes: WorkflowGraphNodeView[]; edges: WorkflowGraphEdge[] }>()
const emit = defineEmits<{ locate: [nodeId: string] }>()
const { t: pt } = useI18n({ useScope: 'local', messages: presentationMessages })
const connections = computed(() => {
  const selected = props.selected?.node
  if (!selected) return []
  const incoming = selected.node_type_id === 'core.io.image-preview'
  return props.edges.filter(edge => edge.target_port === 'presentation' && (incoming ? edge.target_node_id : edge.source_node_id) === selected.node_id).map(edge => {
    const id = incoming ? edge.source_node_id : edge.target_node_id
    const node = props.nodes.find(item => item.node.node_id === id)
    return { id, title: node?.node.parameters.title || node?.title || id, enabled: Boolean(node && node.node.enabled !== false) }
  })
})
</script>
<style scoped>
.presentation-connections { display: flex; flex-direction: column; gap: 8px; font-size: 13px; }
.presentation-connections button { text-align: left; border: 1px solid var(--am-border); border-radius: var(--am-radius-sm); background: var(--am-surface-soft); color: var(--am-text); padding: 8px; overflow-wrap: anywhere; cursor: pointer; }
.presentation-connections small { display: block; color: var(--am-text-muted); }
</style>
