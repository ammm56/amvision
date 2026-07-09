<template>
  <div
    v-for="node in nodes"
    :key="node.node.node_id"
    role="button"
    tabindex="0"
    class="workflow-graph-node"
    :class="{
      'is-selected': selectedNodeId === node.node.node_id,
      'is-runtime-failed': lastPreviewFailureNodeId === node.node.node_id,
      'is-disabled': node.node.enabled === false,
    }"
    :style="{
      left: `${node.x}px`,
      top: `${node.y}px`,
      width: `${node.width}px`,
      height: `${readNodeHeight(node)}px`,
    }"
    @mousedown.stop="emit('startNodeDrag', $event, node)"
    @click.stop="emit('nodeClick', node.node.node_id)"
    @contextmenu.prevent.stop="emit('openNodeContextMenu', $event, node)"
  >
    <span class="workflow-graph-node__title">{{ readTitle(node) }}</span>
    <span v-if="node.node.enabled === false" class="workflow-graph-node__disabled-badge">已禁用</span>
    <span class="workflow-graph-node__type">{{ node.definition?.category || node.node.node_type_id }}</span>
    <div class="workflow-graph-node__ports">
      <div v-for="row in readPortRows(node)" :key="row.key" class="workflow-graph-node__port-row">
        <span
          v-if="row.input"
          class="workflow-graph-port workflow-graph-port--input"
          :class="{
            'is-connected': isPortConnected(node.node.node_id, row.input.name, 'input'),
            'is-selected-endpoint': isSelectedEdgeEndpoint(node.node.node_id, row.input.name, 'input'),
            'is-draft-anchor': isDraftAnchorPort(node.node.node_id, row.input.name, 'input'),
          }"
          :data-node-id="node.node.node_id"
          :data-port-name="row.input.name"
          :data-payload-type-id="row.input.payload_type_id"
          data-port-direction="input"
          @mousedown.stop.prevent="emit('startPortConnection', $event, node, row.input, 'input')"
          @click.stop="emit('selectPortEndpoint', node, row.input, 'input')"
          @contextmenu.prevent.stop="emit('openPortContextMenu', $event, node, row.input, 'input')"
        >
          <span class="workflow-graph-port__dot" aria-hidden="true" />
          <span class="workflow-graph-port__label">{{ readPortLabel(row.input) }}</span>
        </span>
        <span v-else class="workflow-graph-port workflow-graph-port--placeholder" />
        <span
          v-if="row.output"
          class="workflow-graph-port workflow-graph-port--output"
          :class="{
            'is-connected': isPortConnected(node.node.node_id, row.output.name, 'output'),
            'is-selected-endpoint': isSelectedEdgeEndpoint(node.node.node_id, row.output.name, 'output'),
            'is-draft-anchor': isDraftAnchorPort(node.node.node_id, row.output.name, 'output'),
          }"
          :data-node-id="node.node.node_id"
          :data-port-name="row.output.name"
          :data-payload-type-id="row.output.payload_type_id"
          data-port-direction="output"
          @mousedown.stop.prevent="emit('startPortConnection', $event, node, row.output, 'output')"
          @click.stop="emit('selectPortEndpoint', node, row.output, 'output')"
          @contextmenu.prevent.stop="emit('openPortContextMenu', $event, node, row.output, 'output')"
        >
          <span class="workflow-graph-port__label">{{ readPortLabel(row.output) }}</span>
          <span class="workflow-graph-port__dot" aria-hidden="true" />
        </span>
        <span v-else class="workflow-graph-port workflow-graph-port--placeholder" />
      </div>
    </div>
    <WorkflowNodeParameterWidgets
      v-if="hasParameterFields(node)"
      :node="node"
      :fields="readParameterFields(node)"
      :read-label="readParameterLabel"
      :read-enum-value="readParameterEnumIndex"
      :read-enum-options="readParameterEnumOptions"
      :is-boolean="isBooleanParameter"
      :read-boolean-value="readParameterBooleanValue"
      :is-number="isNumberParameter"
      :read-text-value="readParameterTextValue"
      :is-string="isStringParameter"
      :is-json="isJsonParameter"
      :read-json-text-value="readParameterJsonTextValue"
      :read-json-placeholder="readParameterJsonPlaceholder"
      @update-enum="(targetNode, field, value) => emit('updateEnumParameter', targetNode, field, value)"
      @update-checkbox="(targetNode, field, event) => emit('updateCheckboxParameter', targetNode, field, event)"
      @update-number="(targetNode, field, event) => emit('updateNumberParameter', targetNode, field, event)"
      @update-text="(targetNode, field, event) => emit('updateTextParameter', targetNode, field, event)"
      @update-json-draft="(targetNode, field, event) => emit('updateJsonParameterDraft', targetNode, field, event)"
      @commit-json-draft="(targetNode, field, event) => emit('commitJsonParameterDraft', targetNode, field, event)"
    />
    <WorkflowNodePreviewDisplay
      v-if="hasPreviewDisplay(node)"
      :display="requirePreviewDisplay(node)"
      :tooltip="readPreviewDisplayTooltip(requirePreviewDisplay(node))"
      :fallback-title="readTitle(node)"
      @open-display="emit('openPreviewDisplay', $event)"
      @open-image="emit('openPreviewImage', $event)"
    />
  </div>
</template>

<script setup lang="ts">
import WorkflowNodeParameterWidgets from './WorkflowNodeParameterWidgets.vue'
import WorkflowNodePreviewDisplay from './WorkflowNodePreviewDisplay.vue'
import type { PreviewNodeDisplay, PreviewViewerImage } from '../preview/useWorkflowPreviewDisplays'
import type { WorkflowGraphNodeView } from '../nodes/useWorkflowGraphNodeViews'
import type { WorkflowNodePortRowView } from '../nodes/useWorkflowNodeDisplayHelpers'
import type { WorkflowNodeParameterSelectOption, WorkflowNodeParameterSelectValue } from '../parameters/useWorkflowNodeParameters'
import type { NodeParameterUiField, NodePortDefinition } from '../types'

type PortDirection = 'input' | 'output'

const props = defineProps<{
  nodes: WorkflowGraphNodeView[]
  selectedNodeId: string | null
  lastPreviewFailureNodeId: string | null
  readNodeHeight: (node: WorkflowGraphNodeView) => number
  readTitle: (node: WorkflowGraphNodeView) => string
  readPortRows: (node: WorkflowGraphNodeView) => WorkflowNodePortRowView[]
  readPortLabel: (port: NodePortDefinition) => string
  isPortConnected: (nodeId: string, portName: string, direction: PortDirection) => boolean
  isSelectedEdgeEndpoint: (nodeId: string, portName: string, direction: PortDirection) => boolean
  isDraftAnchorPort: (nodeId: string, portName: string, direction: PortDirection) => boolean
  readParameterFields: (node: WorkflowGraphNodeView) => NodeParameterUiField[]
  readParameterLabel: (field: NodeParameterUiField) => string
  readParameterEnumIndex: (node: WorkflowGraphNodeView, field: NodeParameterUiField) => string
  readParameterEnumOptions: (field: NodeParameterUiField) => WorkflowNodeParameterSelectOption[]
  isBooleanParameter: (field: NodeParameterUiField) => boolean
  readParameterBooleanValue: (node: WorkflowGraphNodeView, field: NodeParameterUiField) => boolean
  isNumberParameter: (field: NodeParameterUiField) => boolean
  readParameterTextValue: (node: WorkflowGraphNodeView, field: NodeParameterUiField) => string
  isStringParameter: (field: NodeParameterUiField) => boolean
  isJsonParameter: (field: NodeParameterUiField) => boolean
  readParameterJsonTextValue: (node: WorkflowGraphNodeView, field: NodeParameterUiField) => string
  readParameterJsonPlaceholder: (field: NodeParameterUiField) => string
  readPreviewDisplay: (nodeId: string) => PreviewNodeDisplay | null
  readPreviewDisplayTooltip: (display: PreviewNodeDisplay | null) => string
}>()

const emit = defineEmits<{
  startNodeDrag: [event: MouseEvent, node: WorkflowGraphNodeView]
  nodeClick: [nodeId: string]
  openNodeContextMenu: [event: MouseEvent, node: WorkflowGraphNodeView]
  startPortConnection: [event: MouseEvent, node: WorkflowGraphNodeView, port: NodePortDefinition, direction: PortDirection]
  selectPortEndpoint: [node: WorkflowGraphNodeView, port: NodePortDefinition, direction: PortDirection]
  openPortContextMenu: [event: MouseEvent, node: WorkflowGraphNodeView, port: NodePortDefinition, direction: PortDirection]
  updateEnumParameter: [node: WorkflowGraphNodeView, field: NodeParameterUiField, value: WorkflowNodeParameterSelectValue]
  updateCheckboxParameter: [node: WorkflowGraphNodeView, field: NodeParameterUiField, event: Event]
  updateNumberParameter: [node: WorkflowGraphNodeView, field: NodeParameterUiField, event: Event]
  updateTextParameter: [node: WorkflowGraphNodeView, field: NodeParameterUiField, event: Event]
  updateJsonParameterDraft: [node: WorkflowGraphNodeView, field: NodeParameterUiField, event: Event]
  commitJsonParameterDraft: [node: WorkflowGraphNodeView, field: NodeParameterUiField, event: Event]
  openPreviewDisplay: [display: PreviewNodeDisplay]
  openPreviewImage: [image: PreviewViewerImage]
}>()

function hasParameterFields(node: WorkflowGraphNodeView): boolean {
  return props.readParameterFields(node).length > 0
}

function hasPreviewDisplay(node: WorkflowGraphNodeView): boolean {
  return Boolean(props.readPreviewDisplay(node.node.node_id))
}

function requirePreviewDisplay(node: WorkflowGraphNodeView): PreviewNodeDisplay {
  const display = props.readPreviewDisplay(node.node.node_id)
  if (!display) throw new Error(`preview display missing for node ${node.node.node_id}`)
  return display
}
</script>
