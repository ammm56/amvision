<template>
  <div class="workflow-graph-node-widgets">
    <div
      v-for="field in fields"
      :key="`${node.node.node_id}-${field.parameter_name}`"
      class="workflow-graph-node-widget"
      :class="{ 'is-connected-input': isParameterInputConnected(node, field) }"
      @mousedown.stop
      @click.stop
    >
      <div
        class="workflow-graph-node-widget__label"
        :class="{ 'has-parameter-input': Boolean(readParameterInputPort(node, field)) }"
      >
        <span
          v-if="readParameterInputPort(node, field)"
          class="workflow-graph-port workflow-graph-port--input workflow-graph-parameter-port"
          :class="{
            'is-connected': isParameterInputConnected(node, field),
            'is-selected-endpoint': isSelectedEdgeEndpoint(node.node.node_id, requireParameterInputPort(node, field).name, 'input'),
            'is-draft-anchor': isDraftAnchorPort(node.node.node_id, requireParameterInputPort(node, field).name, 'input'),
          }"
          :data-node-id="node.node.node_id"
          :data-port-name="requireParameterInputPort(node, field).name"
          :data-payload-type-id="requireParameterInputPort(node, field).payload_type_id"
          data-port-direction="input"
          @mousedown.stop.prevent="emit('start-port-connection', $event, node, requireParameterInputPort(node, field), 'input')"
          @click.stop="emit('select-port-endpoint', node, requireParameterInputPort(node, field), 'input')"
          @contextmenu.prevent.stop="emit('open-port-context-menu', $event, node, requireParameterInputPort(node, field), 'input')"
        >
          <span class="workflow-graph-port__dot" aria-hidden="true" />
        </span>
        <span class="workflow-graph-node-widget__label-text">{{ readLabel(field) }}</span>
        <small
          v-if="isParameterInputConnected(node, field)"
          class="workflow-graph-node-widget__connection-source"
          :title="readParameterInputSourceTitle(node, field)"
        >{{ t('workflowEditor.feedback.parameterFromConnection') }}</small>
      </div>
      <SelectField
        v-if="field.enum_options.length"
        :model-value="readEnumValue(node, field)"
        :options="readEnumOptions(field)"
        :disabled="isParameterEditorDisabled(node, field)"
        :aria-label="readLabel(field)"
        @update:model-value="emit('update-enum', node, field, $event)"
      />
      <div
        v-else-if="isModelInferenceDeploymentField(node, field)"
        class="workflow-graph-node-widget__deployment"
      >
        <input
          :value="readTextValue(node, field)"
          readonly
          :title="readTextValue(node, field) || t('workflowEditor.deploymentPicker.notSelected')"
          :placeholder="t('workflowEditor.deploymentPicker.selectPlaceholder')"
        >
        <button
          type="button"
          :disabled="isParameterEditorDisabled(node, field)"
          :title="t('workflowEditor.deploymentPicker.selectApplicable')"
          :aria-label="t('workflowEditor.deploymentPicker.selectAria')"
          @mousedown.stop
          @click.stop="emit('select-deployment-instance', node)"
        >
          <ListFilter :size="13" />
          {{ t('workflowEditor.deploymentPicker.selectAction') }}
        </button>
      </div>
      <WorkflowGraphCheckbox
        v-else-if="isBoolean(field)"
        :checked="readBooleanValue(node, field)"
        :disabled="isParameterEditorDisabled(node, field)"
        :aria-label="readLabel(field)"
        @change="emit('update-checkbox', node, field, $event)"
      />
      <input
        v-else-if="isNumber(field)"
        type="number"
        :min="readWorkflowNumericParameterInputAttributes(field).min"
        :max="readWorkflowNumericParameterInputAttributes(field).max"
        :step="readWorkflowNumericParameterInputAttributes(field).step"
        :value="readTextValue(node, field)"
        :disabled="isParameterEditorDisabled(node, field)"
        :aria-label="readLabel(field)"
        @input="emit('update-number', node, field, $event)"
      />
      <input
        v-else-if="isString(field)"
        :value="readTextValue(node, field)"
        :disabled="isParameterEditorDisabled(node, field)"
        :aria-label="readLabel(field)"
        @input="emit('update-text', node, field, $event)"
      />
      <WorkflowParameterColorMap
        v-else-if="isColorMap(field)"
        :model-value="readValue(node, field)"
        :label="readLabel(field)"
        :key-label="readColorMapSchemaTitle(field, 'propertyNames', t('workflowEditor.colorMap.keyLabel'))"
        :value-label="readColorMapSchemaTitle(field, 'additionalProperties', t('workflowEditor.colorMap.valueLabel'))"
        :disabled="isParameterEditorDisabled(node, field)"
        @update:model-value="emit('update-value', node, field, $event)"
      />
      <template v-else-if="isJson(field)">
        <textarea
          :value="readJsonTextValue(node, field)"
          :disabled="isParameterEditorDisabled(node, field)"
          :aria-label="readLabel(field)"
          :placeholder="readJsonPlaceholder(field)"
          @input="emit('update-json-draft', node, field, $event)"
          @change="emit('commit-json-draft', node, field, $event)"
        />
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ListFilter } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

import SelectField from '@/shared/ui/components/Select.vue'
import WorkflowGraphCheckbox from './WorkflowGraphCheckbox.vue'
import WorkflowParameterColorMap from './WorkflowParameterColorMap.vue'
import { readNodeParameterInputPort } from '../parameters/parameter-input-bindings'
import { isModelInferenceDeploymentField } from '../parameters/useWorkflowDeploymentInstancePicker'
import { readWorkflowNumericParameterInputAttributes } from '../parameters/numeric-parameter-input'
import type { NodeDefinition, NodeParameterUiField, NodePortDefinition, WorkflowGraphNode } from '../types'

type SelectValue = string | number | boolean | null

const { t } = useI18n()

interface SelectOption {
  label: string
  value: SelectValue
  description?: string
}

interface WorkflowNodeParameterNode {
  node: WorkflowGraphNode
  definition: NodeDefinition | null
  title: string
  x: number
  y: number
  width: number
  inputs: NodePortDefinition[]
  outputs: NodePortDefinition[]
}

const props = defineProps<{
  node: WorkflowNodeParameterNode
  fields: NodeParameterUiField[]
  readLabel: (field: NodeParameterUiField) => string
  readEnumValue: (node: WorkflowNodeParameterNode, field: NodeParameterUiField) => string
  readEnumOptions: (field: NodeParameterUiField) => SelectOption[]
  isBoolean: (field: NodeParameterUiField) => boolean
  readBooleanValue: (node: WorkflowNodeParameterNode, field: NodeParameterUiField) => boolean
  isNumber: (field: NodeParameterUiField) => boolean
  readTextValue: (node: WorkflowNodeParameterNode, field: NodeParameterUiField) => string
  isString: (field: NodeParameterUiField) => boolean
  isColorMap: (field: NodeParameterUiField) => boolean
  readValue: (node: WorkflowNodeParameterNode, field: NodeParameterUiField) => unknown
  isJson: (field: NodeParameterUiField) => boolean
  readJsonTextValue: (node: WorkflowNodeParameterNode, field: NodeParameterUiField) => string
  readJsonPlaceholder: (field: NodeParameterUiField) => string
  isPortConnected: (nodeId: string, portName: string, direction: 'input' | 'output') => boolean
  isSelectedEdgeEndpoint: (nodeId: string, portName: string, direction: 'input' | 'output') => boolean
  isDraftAnchorPort: (nodeId: string, portName: string, direction: 'input' | 'output') => boolean
  readInputSourceLabel: (nodeId: string, portName: string) => string
}>()

const emit = defineEmits<{
  'update-enum': [node: WorkflowNodeParameterNode, field: NodeParameterUiField, value: SelectValue]
  'update-checkbox': [node: WorkflowNodeParameterNode, field: NodeParameterUiField, event: Event]
  'update-number': [node: WorkflowNodeParameterNode, field: NodeParameterUiField, event: Event]
  'update-text': [node: WorkflowNodeParameterNode, field: NodeParameterUiField, event: Event]
  'update-value': [node: WorkflowNodeParameterNode, field: NodeParameterUiField, value: unknown]
  'update-json-draft': [node: WorkflowNodeParameterNode, field: NodeParameterUiField, event: Event]
  'commit-json-draft': [node: WorkflowNodeParameterNode, field: NodeParameterUiField, event: Event]
  'select-deployment-instance': [node: WorkflowNodeParameterNode]
  'start-port-connection': [event: MouseEvent, node: WorkflowNodeParameterNode, port: NodePortDefinition, direction: 'input']
  'select-port-endpoint': [node: WorkflowNodeParameterNode, port: NodePortDefinition, direction: 'input']
  'open-port-context-menu': [event: MouseEvent, node: WorkflowNodeParameterNode, port: NodePortDefinition, direction: 'input']
}>()

function readParameterInputPort(node: WorkflowNodeParameterNode, field: NodeParameterUiField): NodePortDefinition | null {
  return readNodeParameterInputPort(node.definition, field.parameter_name)
}

function requireParameterInputPort(node: WorkflowNodeParameterNode, field: NodeParameterUiField): NodePortDefinition {
  const port = readParameterInputPort(node, field)
  if (!port) throw new Error(`parameter input port missing: ${node.node.node_id}/${field.parameter_name}`)
  return port
}

function isParameterInputConnected(node: WorkflowNodeParameterNode, field: NodeParameterUiField): boolean {
  const port = readParameterInputPort(node, field)
  return port ? props.isPortConnected(node.node.node_id, port.name, 'input') : false
}

function isParameterEditorDisabled(node: WorkflowNodeParameterNode, field: NodeParameterUiField): boolean {
  return field.readonly || isParameterInputConnected(node, field)
}

function readParameterInputSourceTitle(node: WorkflowNodeParameterNode, field: NodeParameterUiField): string {
  const port = readParameterInputPort(node, field)
  if (!port) return ''
  const source = props.readInputSourceLabel(node.node.node_id, port.name)
  return source
    ? t('workflowEditor.feedback.parameterConnectionSource', { source })
    : t('workflowEditor.feedback.parameterFromConnection')
}

function readColorMapSchemaTitle(
  field: NodeParameterUiField,
  schemaKey: 'propertyNames' | 'additionalProperties',
  fallback: string,
): string {
  const schema = field.json_schema[schemaKey]
  if (!schema || typeof schema !== 'object' || Array.isArray(schema)) return fallback
  const title = (schema as Record<string, unknown>).title
  return typeof title === 'string' && title.trim() ? title.trim() : fallback
}
</script>
