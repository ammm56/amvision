<template>
  <div
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
      height: `${visualHeight}px`,
    }"
    @mousedown.stop="emit('startNodeDrag', $event, node)"
    @click.stop="emit('nodeClick', node.node.node_id)"
    @contextmenu.prevent.stop="emit('openNodeContextMenu', $event, node)"
  >
    <span class="workflow-graph-node__title" :title="readTitle(node)">{{ readTitle(node) }}</span>
    <span v-if="node.node.enabled === false" class="workflow-graph-node__disabled-badge">{{ t('workflowEditor.editor.disabled') }}</span>
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
      :is-color-map="isColorMapParameter"
      :read-value="readParameterValue"
      :is-json="isJsonParameter"
      :read-json-text-value="readParameterJsonTextValue"
      :read-json-placeholder="readParameterJsonPlaceholder"
      :is-port-connected="isPortConnected"
      :is-selected-edge-endpoint="isSelectedEdgeEndpoint"
      :is-draft-anchor-port="isDraftAnchorPort"
      :read-input-source-label="readInputSourceLabel"
      @update-enum="(targetNode, field, value) => emit('updateEnumParameter', targetNode, field, value)"
      @update-checkbox="(targetNode, field, event) => emit('updateCheckboxParameter', targetNode, field, event)"
      @update-number="(targetNode, field, event) => emit('updateNumberParameter', targetNode, field, event)"
      @update-text="(targetNode, field, event) => emit('updateTextParameter', targetNode, field, event)"
      @update-value="(targetNode, field, value) => emit('updateValueParameter', targetNode, field, value)"
      @update-json-draft="(targetNode, field, event) => emit('updateJsonParameterDraft', targetNode, field, event)"
      @commit-json-draft="(targetNode, field, event) => emit('commitJsonParameterDraft', targetNode, field, event)"
      @select-deployment-instance="(targetNode) => emit('selectDeploymentInstance', targetNode)"
      @start-port-connection="(event, targetNode, port, direction) => emit('startPortConnection', event, targetNode, port, direction)"
      @select-port-endpoint="(targetNode, port, direction) => emit('selectPortEndpoint', targetNode, port, direction)"
      @open-port-context-menu="(event, targetNode, port, direction) => emit('openPortContextMenu', event, targetNode, port, direction)"
    />
    <WorkflowNodePreviewDisplay
      v-if="previewDisplay"
      :display="previewDisplay!"
      :tooltip="readPreviewDisplayTooltip(previewDisplay!)"
      :fallback-title="readTitle(node)"
      @open-display="emit('openPreviewDisplay', $event)"
      @open-image="emit('openPreviewImage', $event)"
    />
    <span
      v-if="durationLabel"
      class="workflow-graph-node__preview-duration"
      :title="durationLabel"
    >{{ durationLabel }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useTranslation } from '@/platform/i18n'

import WorkflowNodeParameterWidgets from './WorkflowNodeParameterWidgets.vue'
import WorkflowNodePreviewDisplay from './WorkflowNodePreviewDisplay.vue'
import { formatPreviewNodeDuration } from '../preview/workflow-preview-node-timings'
import type { WorkflowGraphNodeView } from '../nodes/useWorkflowGraphNodeViews'
import type { WorkflowGraphNodeProps, WorkflowGraphNodeEvents } from './workflow-graph-node.types'

const { t } = useTranslation()
const props = defineProps<WorkflowGraphNodeProps>()
const emit = defineEmits<WorkflowGraphNodeEvents>()
// 将共享预览索引的失效限制在读取阶段；未变化的节点不重新渲染参数与端口。
const previewDisplay = computed(() => props.readPreviewDisplay(props.node.node.node_id))
const visualHeight = computed(() => props.readNodeHeight(props.node))
const durationLabel = computed(() => {
  const nodeId = props.node.node.node_id
  const durationMs = props.readPreviewDurationMs(nodeId)
  return [props.readPreviewStatus?.(nodeId), durationMs === null ? '' : formatPreviewNodeDuration(durationMs)].filter(Boolean).join(' · ')
})

function hasParameterFields(node: WorkflowGraphNodeView): boolean {
  return props.readParameterFields(node).length > 0
}

</script>
