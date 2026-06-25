import type { ComputedRef } from 'vue'

import type { SupportedLocale } from '@/platform/i18n'

import { resolveNodeDefinitionDisplayName, resolveNodeParameterDisplayName, resolveNodePortDisplayName } from '../node-definition-localization'
import type { NodeDefinition, NodeParameterUiField, NodePortDefinition, WorkflowGraphNode } from '../types'

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
}

export function useWorkflowNodeDisplayHelpers(options: WorkflowNodeDisplayHelperOptions) {
  function readGraphNodeTitle(node: WorkflowNodeDisplayView): string {
    return node.definition ? resolveNodeDefinitionDisplayName(node.definition, options.currentLocale.value) : node.title
  }

  function readNodePortLabel(port: NodePortDefinition): string {
    return resolveNodePortDisplayName(port, options.currentLocale.value) || port.name
  }

  function readNodeParameterLabel(field: NodeParameterUiField): string {
    return resolveNodeParameterDisplayName(field, options.currentLocale.value) || field.parameter_name
  }

  function nodePortRows(node: WorkflowNodeDisplayView): WorkflowNodePortRowView[] {
    const rowCount = Math.max(node.inputs.length, node.outputs.length)
    return Array.from({ length: rowCount }, (_, index) => ({
      key: `${node.node.node_id}-port-row-${index}`,
      input: node.inputs[index] ?? null,
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
