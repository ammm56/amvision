import { translate } from '@/platform/i18n'
import type { NodeDefinition, WorkflowGraphTemplate } from '../types'
import type { WorkflowValidationIssue } from './useWorkflowPreflight'

export function validateRequiredInputConnections(
  template: WorkflowGraphTemplate,
  definitions: ReadonlyMap<string, NodeDefinition>,
): WorkflowValidationIssue | null {
  const enabled = new Set(template.nodes.filter(node => node.enabled !== false).map(node => node.node_id))
  const connected = new Map<string, Set<string>>()
  const add = (id: string, port: string) => {
    if (!connected.has(id)) connected.set(id, new Set())
    connected.get(id)!.add(port)
  }
  for (const input of template.template_inputs) add(input.target_node_id, input.target_port)
  for (const edge of template.edges) {
    if (enabled.has(edge.source_node_id) && enabled.has(edge.target_node_id)) add(edge.target_node_id, edge.target_port)
  }
  for (const node of template.nodes) {
    if (!enabled.has(node.node_id)) continue
    const definition = definitions.get(node.node_type_id)
    if (!definition) return {
      message: translate('workflowEditor.validation.nodeTypeUnavailable', { node: node.node_id, nodeType: node.node_type_id }),
      nodeId: node.node_id,
    }
    for (const port of definition.input_ports) {
      if (port.required && !connected.get(node.node_id)?.has(port.name)) return {
        message: translate('workflowEditor.validation.requiredPortDisconnected', { node: node.node_id, port: port.name }),
        nodeId: node.node_id,
      }
    }
  }
  return null
}
