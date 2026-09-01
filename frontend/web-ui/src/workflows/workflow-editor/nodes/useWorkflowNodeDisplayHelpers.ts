import type { ComputedRef, Ref } from 'vue'

import type { SupportedLocale } from '@/platform/i18n'

import { resolveNodeDefinitionDisplayName, resolveNodeParameterDisplayName, resolveNodePortDisplayName } from '../node-definition-localization'
import { findNodeParameterInputBinding, readRegularNodeInputPorts } from '../parameters/parameter-input-bindings'
import type { NodeDefinition, NodeParameterUiField, NodePortDefinition, WorkflowGraphEdge, WorkflowGraphNode } from '../types'

export interface WorkflowNodeDisplayView {
  node: WorkflowGraphNode
  definition: NodeDefinition | null
  title: string
  inputs: NodePortDefinition[]
  outputs: NodePortDefinition[]
}

export interface WorkflowNodePortRowView {
  key: string
  input: NodePortDefinition | null
  output: NodePortDefinition | null
}

export interface WorkflowNodeDisplayHelperOptions {
  currentLocale: ComputedRef<SupportedLocale>
  graphEdges: Ref<WorkflowGraphEdge[]>
}

export function useWorkflowNodeDisplayHelpers(options: WorkflowNodeDisplayHelperOptions) {
  function readGraphNodeTitle(node: WorkflowNodeDisplayView): string {
    if (!node.definition) return node.title
    const baseTitle = resolveNodeDefinitionDisplayName(node.definition, options.currentLocale.value)
    const titleParameter = node.definition.metadata.title_parameter
    if (typeof titleParameter !== 'string' || !titleParameter.trim()) return baseTitle
    const parameterBinding = findNodeParameterInputBinding(node.definition, titleParameter)
    if (parameterBinding && options.graphEdges.value.some((edge) => (
      edge.target_node_id === node.node.node_id
      && edge.target_port === parameterBinding.input_port_name
    ))) return baseTitle
    const parameterValue = node.node.parameters[titleParameter]
    if (typeof parameterValue === 'string' && parameterValue.trim()) {
      return `${baseTitle} · ${parameterValue.trim()}`
    }
    if (typeof parameterValue === 'number' && Number.isFinite(parameterValue)) {
      return `${baseTitle} · ${parameterValue}`
    }
    return baseTitle
  }

  function readNodePortLabel(port: NodePortDefinition): string {
    return resolveNodePortDisplayName(port, options.currentLocale.value) || port.name
  }

  function readNodeParameterLabel(field: NodeParameterUiField): string {
    return resolveNodeParameterDisplayName(field, options.currentLocale.value) || field.parameter_name
  }

  function nodePortRows(node: WorkflowNodeDisplayView): WorkflowNodePortRowView[] {
    const fields = node.definition?.parameter_ui_schema?.fields.filter((field) => !field.hidden) ?? []
    const regularInputs = readRegularNodeInputPorts(node.definition, node.inputs, fields)
    const rowCount = Math.max(regularInputs.length, node.outputs.length)
    return Array.from({ length: rowCount }, (_, index) => ({
      key: `${node.node.node_id}-port-row-${index}`,
      input: regularInputs[index] ?? null,
      output: node.outputs[index] ?? null,
    }))
  }

  return {
    readGraphNodeTitle,
    readNodePortLabel,
    readNodeParameterLabel,
    nodePortRows,
  }
}
