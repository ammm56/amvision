<template>
  <div class="workflow-graph-node-widgets">
    <label
      v-for="field in fields"
      :key="`${node.node.node_id}-${field.parameter_name}`"
      class="workflow-graph-node-widget"
      @mousedown.stop
      @click.stop
    >
      <div class="workflow-graph-node-widget__label">
        <span>{{ readLabel(field) }}</span>
      </div>
      <SelectField
        v-if="field.enum_options.length"
        :model-value="readEnumValue(node, field)"
        :options="readEnumOptions(field)"
        :disabled="field.readonly"
        @update:model-value="emit('update-enum', node, field, $event)"
      />
      <input
        v-else-if="isBoolean(field)"
        type="checkbox"
        :checked="readBooleanValue(node, field)"
        :disabled="field.readonly"
        @change="emit('update-checkbox', node, field, $event)"
      />
      <input
        v-else-if="isNumber(field)"
        type="number"
        step="any"
        :value="readTextValue(node, field)"
        :disabled="field.readonly"
        @change="emit('update-number', node, field, $event)"
      />
      <input
        v-else-if="isString(field)"
        :value="readTextValue(node, field)"
        :disabled="field.readonly"
        @input="emit('update-text', node, field, $event)"
      />
      <template v-else-if="isJson(field)">
        <textarea
          :value="readJsonTextValue(node, field)"
          :disabled="field.readonly"
          :placeholder="readJsonPlaceholder(field)"
          @input="emit('update-json-draft', node, field, $event)"
          @change="emit('commit-json-draft', node, field, $event)"
        />
      </template>
    </label>
  </div>
</template>

<script setup lang="ts">
import SelectField from '@/shared/ui/components/Select.vue'
import type { NodeDefinition, NodeParameterUiField, NodePortDefinition, WorkflowGraphNode } from '../types'

type SelectValue = string | number | boolean | null

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

defineProps<{
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
  isJson: (field: NodeParameterUiField) => boolean
  readJsonTextValue: (node: WorkflowNodeParameterNode, field: NodeParameterUiField) => string
  readJsonPlaceholder: (field: NodeParameterUiField) => string
}>()

const emit = defineEmits<{
  'update-enum': [node: WorkflowNodeParameterNode, field: NodeParameterUiField, value: SelectValue]
  'update-checkbox': [node: WorkflowNodeParameterNode, field: NodeParameterUiField, event: Event]
  'update-number': [node: WorkflowNodeParameterNode, field: NodeParameterUiField, event: Event]
  'update-text': [node: WorkflowNodeParameterNode, field: NodeParameterUiField, event: Event]
  'update-json-draft': [node: WorkflowNodeParameterNode, field: NodeParameterUiField, event: Event]
  'commit-json-draft': [node: WorkflowNodeParameterNode, field: NodeParameterUiField, event: Event]
}>()
</script>
