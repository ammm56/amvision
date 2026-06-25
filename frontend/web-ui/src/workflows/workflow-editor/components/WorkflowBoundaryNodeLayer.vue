<template>
  <div
    v-for="boundary in boundaries"
    :key="boundary.id"
    role="button"
    tabindex="0"
    class="workflow-graph-boundary-node"
    :class="[
      `workflow-graph-boundary-node--${boundary.kind}`,
      {
        'is-selected': selectedBoundaryKind === boundary.kind,
        'is-dragging': draggedBoundaryKind === boundary.kind,
      },
    ]"
    :style="{
      left: `${boundary.x}px`,
      top: `${boundary.y}px`,
      width: `${boundary.width}px`,
      height: `${readBoundaryHeight(boundary)}px`,
    }"
    @mousedown.stop="emit('startBoundaryDrag', $event, boundary)"
    @click.stop="emit('selectBoundary', boundary.kind)"
    @contextmenu.prevent.stop="emit('openBoundaryContextMenu', $event, boundary)"
  >
    <div class="workflow-graph-boundary-node__header">
      <span class="workflow-graph-boundary-node__title">{{ boundary.title }}</span>
      <span class="workflow-graph-boundary-node__type">{{ boundary.description }}</span>
    </div>
    <div class="workflow-graph-boundary-node__ports">
      <span
        v-for="binding in boundary.bindings"
        :key="`${boundary.id}-${binding.binding_id}`"
        class="workflow-graph-port workflow-graph-boundary-port"
        :class="[
          `workflow-graph-port--${boundary.portDirection}`,
          {
            'is-connected': isBoundaryPortConnected(boundary.kind, binding),
            'is-selected-endpoint': selectedBoundaryKind === boundary.kind,
          },
        ]"
        :data-node-id="boundary.id"
        :data-port-name="binding.binding_id"
        :data-payload-type-id="getBindingPayloadTypeId(binding)"
        :data-port-direction="boundary.portDirection"
        @mousedown.stop="emit('startBoundaryPortConnection', $event, boundary, binding)"
        @click.stop="emit('selectBoundaryBinding', boundary.kind, binding)"
        @contextmenu.prevent.stop="emit('openBoundaryPortContextMenu', $event, boundary, binding)"
      >
        <span v-if="boundary.portDirection === 'input'" class="workflow-graph-port__dot" aria-hidden="true" />
        <span class="workflow-graph-port__label">
          <strong>{{ binding.binding_id }}</strong>
          <small>{{ getBindingPayloadTypeId(binding) || 'unknown' }}</small>
        </span>
        <span v-if="boundary.portDirection === 'output'" class="workflow-graph-port__dot" aria-hidden="true" />
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { WorkflowBoundaryKind } from '../bindings/useWorkflowPublicBindings'
import type { WorkflowBoundaryNodeView } from '../bindings/useWorkflowBoundaryNodes'
import type { FlowApplicationBinding } from '../types'

defineProps<{
  boundaries: WorkflowBoundaryNodeView[]
  selectedBoundaryKind: WorkflowBoundaryKind | null
  draggedBoundaryKind: WorkflowBoundaryKind | null
  readBoundaryHeight: (boundary: WorkflowBoundaryNodeView) => number
  isBoundaryPortConnected: (kind: WorkflowBoundaryKind, binding: FlowApplicationBinding) => boolean
  getBindingPayloadTypeId: (binding: FlowApplicationBinding) => string
}>()

const emit = defineEmits<{
  startBoundaryDrag: [event: MouseEvent, boundary: WorkflowBoundaryNodeView]
  selectBoundary: [kind: WorkflowBoundaryKind]
  openBoundaryContextMenu: [event: MouseEvent, boundary: WorkflowBoundaryNodeView]
  startBoundaryPortConnection: [event: MouseEvent, boundary: WorkflowBoundaryNodeView, binding: FlowApplicationBinding]
  selectBoundaryBinding: [kind: WorkflowBoundaryKind, binding: FlowApplicationBinding]
  openBoundaryPortContextMenu: [event: MouseEvent, boundary: WorkflowBoundaryNodeView, binding: FlowApplicationBinding]
}>()
</script>
