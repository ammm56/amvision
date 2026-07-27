import type { ComputedRef, Ref } from 'vue'

import { translate } from '@/platform/i18n'
import type { WorkflowBoundaryKind } from '../bindings/useWorkflowPublicBindings'
import type {
  FlowApplication,
  NodeDefinition,
  NodePortDefinition,
  WorkflowGraphEdge,
  WorkflowGraphTemplate,
} from '../types'

export interface WorkflowPreflightNodeView {
  node: {
    node_id: string
    node_type_id: string
  }
  inputs: NodePortDefinition[]
  outputs: NodePortDefinition[]
}

export interface WorkflowValidationIssue {
  message: string
  nodeId?: string
  edgeId?: string
  boundaryKind?: WorkflowBoundaryKind
  bindingId?: string
}

export interface WorkflowValidationSelection {
  nodeId: string | null
  edgeId: string | null
  boundaryKind: WorkflowBoundaryKind | null
}

export interface WorkflowPreflightOptions<NodeView extends WorkflowPreflightNodeView> {
  graphNodes: Ref<NodeView[]>
  graphEdges: Ref<WorkflowGraphEdge[]>
  nodeDefinitionsById: ComputedRef<Map<string, NodeDefinition>>
  portsCanConnect: (sourcePort: NodePortDefinition, targetPort: NodePortDefinition) => boolean
  focusGraphNode: (nodeId: string) => void
  setSelection: (selection: WorkflowValidationSelection) => void
  clearTransientUi: () => void
  setErrorMessage: (message: string | null) => void
  setStatusMessage: (message: string | null) => void
}

export function useWorkflowPreflight<NodeView extends WorkflowPreflightNodeView>(options: WorkflowPreflightOptions<NodeView>) {
  function runWorkflowPreflight(template: WorkflowGraphTemplate, application: FlowApplication): WorkflowValidationIssue | null {
    if (template.nodes.length === 0) return { message: translate('workflowEditor.validation.nodeRequired') }
    const duplicateNodeId = findDuplicateValue(template.nodes.map((node) => node.node_id))
    if (duplicateNodeId) return { message: duplicateIdMessage('node', duplicateNodeId), nodeId: duplicateNodeId }
    const duplicateEdgeId = findDuplicateValue(template.edges.map((edge) => edge.edge_id))
    if (duplicateEdgeId) return { message: duplicateIdMessage('edge', duplicateEdgeId), edgeId: duplicateEdgeId }
    const duplicateInputId = findDuplicateValue(template.template_inputs.map((input) => input.input_id))
    if (duplicateInputId) return { message: duplicateIdMessage('appInput', duplicateInputId), boundaryKind: 'entry', bindingId: duplicateInputId }
    const duplicateOutputId = findDuplicateValue(template.template_outputs.map((output) => output.output_id))
    if (duplicateOutputId) return { message: duplicateIdMessage('appOutput', duplicateOutputId), boundaryKind: 'result', bindingId: duplicateOutputId }
    const duplicateGroupId = findDuplicateValue(template.groups.map((group) => group.group_id))
    if (duplicateGroupId) return { message: duplicateIdMessage('nodeGroup', duplicateGroupId) }

    const nodeViewsById = new Map(options.graphNodes.value.map((node) => [node.node.node_id, node]))
    const inputUsage = new Map<string, string[]>()
    for (const node of template.nodes) {
      const graphNode = nodeViewsById.get(node.node_id)
      if (!graphNode) return { message: translate('workflowEditor.validation.nodeViewMissing', { node: node.node_id }), nodeId: node.node_id }
      if (!options.nodeDefinitionsById.value.has(node.node_type_id)) return {
        message: translate('workflowEditor.validation.nodeTypeUnavailable', { node: node.node_id, nodeType: node.node_type_id }),
        nodeId: node.node_id,
      }
    }

    for (const group of template.groups) {
      if (!group.group_id.trim()) return { message: translate('workflowEditor.validation.groupIdRequired') }
      if (!group.name.trim()) return { message: translate('workflowEditor.validation.groupNameRequired', { group: group.group_id }) }
      if (!Number.isFinite(group.rect.x) || !Number.isFinite(group.rect.y) || !Number.isFinite(group.rect.width) || !Number.isFinite(group.rect.height)) {
        return { message: translate('workflowEditor.validation.groupRectInvalid', { group: group.group_id }) }
      }
      if (group.rect.width <= 0 || group.rect.height <= 0) return {
        message: translate('workflowEditor.validation.groupSizeInvalid', { group: group.group_id }),
      }
      const duplicateMemberNodeId = findDuplicateValue(group.member_node_ids)
      if (duplicateMemberNodeId) return {
        message: translate('workflowEditor.validation.groupMemberDuplicate', { group: group.group_id, node: duplicateMemberNodeId }),
        nodeId: duplicateMemberNodeId,
      }
      for (const memberNodeId of group.member_node_ids) {
        if (!nodeViewsById.has(memberNodeId)) return {
          message: translate('workflowEditor.validation.groupNodeMissing', { group: group.group_id, node: memberNodeId }),
        }
      }
    }

    for (const edge of template.edges) {
      const sourceNode = nodeViewsById.get(edge.source_node_id)
      const targetNode = nodeViewsById.get(edge.target_node_id)
      if (!sourceNode) return { message: translate('workflowEditor.validation.edgeSourceNodeMissing', { edge: edge.edge_id, node: edge.source_node_id }), edgeId: edge.edge_id }
      if (!targetNode) return { message: translate('workflowEditor.validation.edgeTargetNodeMissing', { edge: edge.edge_id, node: edge.target_node_id }), edgeId: edge.edge_id }
      const sourcePort = sourceNode.outputs.find((port) => port.name === edge.source_port)
      const targetPort = targetNode.inputs.find((port) => port.name === edge.target_port)
      if (!sourcePort) return {
        message: translate('workflowEditor.validation.edgeSourcePortMissing', {
          edge: edge.edge_id,
          port: `${edge.source_node_id}.${edge.source_port}`,
        }),
        nodeId: edge.source_node_id,
        edgeId: edge.edge_id,
      }
      if (!targetPort) return {
        message: translate('workflowEditor.validation.edgeTargetPortMissing', {
          edge: edge.edge_id,
          port: `${edge.target_node_id}.${edge.target_port}`,
        }),
        nodeId: edge.target_node_id,
        edgeId: edge.edge_id,
      }
      if (!options.portsCanConnect(sourcePort, targetPort)) return {
        message: translate('workflowEditor.validation.edgePayloadMismatch', {
          edge: edge.edge_id,
          source: sourcePort.payload_type_id || 'unknown',
          target: targetPort.payload_type_id || 'unknown',
        }),
        edgeId: edge.edge_id,
      }
      const issue = registerInputUsage(
        inputUsage,
        targetNode,
        targetPort,
        translate('workflowEditor.validation.edgeLabel', { edge: edge.edge_id }),
      )
      if (issue) return { ...issue, edgeId: edge.edge_id }
    }

    for (const input of template.template_inputs) {
      const targetNode = nodeViewsById.get(input.target_node_id)
      if (!targetNode) return {
        message: translate('workflowEditor.validation.inputTargetNodeMissing', { input: input.input_id, node: input.target_node_id }),
        boundaryKind: 'entry',
        bindingId: input.input_id,
      }
      const targetPort = targetNode.inputs.find((port) => port.name === input.target_port)
      if (!targetPort) return {
        message: translate('workflowEditor.validation.inputTargetPortMissing', {
          input: input.input_id,
          port: `${input.target_node_id}.${input.target_port}`,
        }),
        nodeId: input.target_node_id,
        boundaryKind: 'entry',
        bindingId: input.input_id,
      }
      if (input.payload_type_id !== targetPort.payload_type_id) return {
        message: translate('workflowEditor.validation.inputPayloadMismatch', {
          input: input.input_id,
          source: input.payload_type_id || 'unknown',
          target: targetPort.payload_type_id || 'unknown',
        }),
        nodeId: input.target_node_id,
        boundaryKind: 'entry',
        bindingId: input.input_id,
      }
      const issue = registerInputUsage(
        inputUsage,
        targetNode,
        targetPort,
        translate('workflowEditor.validation.inputLabel', { input: input.input_id }),
      )
      if (issue) return { ...issue, nodeId: input.target_node_id, boundaryKind: 'entry', bindingId: input.input_id }
    }

    for (const output of template.template_outputs) {
      const sourceNode = nodeViewsById.get(output.source_node_id)
      if (!sourceNode) return {
        message: translate('workflowEditor.validation.outputSourceNodeMissing', { output: output.output_id, node: output.source_node_id }),
        boundaryKind: 'result',
        bindingId: output.output_id,
      }
      const sourcePort = sourceNode.outputs.find((port) => port.name === output.source_port)
      if (!sourcePort) return {
        message: translate('workflowEditor.validation.outputSourcePortMissing', {
          output: output.output_id,
          port: `${output.source_node_id}.${output.source_port}`,
        }),
        nodeId: output.source_node_id,
        boundaryKind: 'result',
        bindingId: output.output_id,
      }
      if (output.payload_type_id !== sourcePort.payload_type_id) return {
        message: translate('workflowEditor.validation.outputPayloadMismatch', {
          output: output.output_id,
          source: sourcePort.payload_type_id || 'unknown',
          target: output.payload_type_id || 'unknown',
        }),
        nodeId: output.source_node_id,
        boundaryKind: 'result',
        bindingId: output.output_id,
      }
    }

    if (application.template_ref.template_id !== template.template_id) return {
      message: translate('workflowEditor.validation.templateIdMismatch', {
        referenced: application.template_ref.template_id,
        current: template.template_id,
      }),
    }
    if (application.template_ref.template_version !== template.template_version) return {
      message: translate('workflowEditor.validation.templateVersionMismatch', {
        referenced: application.template_ref.template_version,
        current: template.template_version,
      }),
    }

    const duplicateBindingId = findDuplicateValue(application.bindings.map((binding) => binding.binding_id))
    if (duplicateBindingId) return {
      message: duplicateIdMessage('publicBinding', duplicateBindingId),
      boundaryKind: findBindingBoundaryKind(application, duplicateBindingId),
      bindingId: duplicateBindingId,
    }

    const templateInputIds = new Set(template.template_inputs.map((input) => input.input_id))
    const templateOutputIds = new Set(template.template_outputs.map((output) => output.output_id))
    const inputBindingCounts = new Map<string, number>()
    const outputBindingCounts = new Map<string, number>()
    for (const binding of application.bindings) {
      const boundaryKind = binding.direction === 'input' ? 'entry' : 'result'
      if (!binding.binding_id.trim()) return {
        message: translate('workflowEditor.validation.publicBindingIdRequired'),
        boundaryKind,
        bindingId: binding.binding_id,
      }
      if (!binding.template_port_id.trim()) return {
        message: translate('workflowEditor.validation.templatePortRequired', { binding: binding.binding_id }),
        boundaryKind,
        bindingId: binding.binding_id,
      }
      if (!binding.binding_kind.trim()) return {
        message: translate('workflowEditor.validation.bindingKindRequired', { binding: binding.binding_id }),
        boundaryKind,
        bindingId: binding.binding_id,
      }
      if (binding.direction === 'input') {
        if (!templateInputIds.has(binding.template_port_id)) return {
          message: translate('workflowEditor.validation.inputBindingTargetMissing', {
            binding: binding.binding_id,
            input: binding.template_port_id,
          }),
          boundaryKind,
          bindingId: binding.binding_id,
        }
        const templateInput = template.template_inputs.find((input) => input.input_id === binding.template_port_id)
        if (templateInput?.required && !binding.required) return {
          message: translate('workflowEditor.validation.requiredInputOptional', { binding: binding.binding_id }),
          boundaryKind,
          bindingId: binding.binding_id,
        }
        inputBindingCounts.set(binding.template_port_id, (inputBindingCounts.get(binding.template_port_id) ?? 0) + 1)
        if ((inputBindingCounts.get(binding.template_port_id) ?? 0) > 1) return {
          message: translate('workflowEditor.validation.inputBindingDuplicate', { input: binding.template_port_id }),
          boundaryKind,
          bindingId: binding.binding_id,
        }
        continue
      }
      if (!templateOutputIds.has(binding.template_port_id)) return {
        message: translate('workflowEditor.validation.outputBindingTargetMissing', {
          binding: binding.binding_id,
          output: binding.template_port_id,
        }),
        boundaryKind,
        bindingId: binding.binding_id,
      }
      outputBindingCounts.set(binding.template_port_id, (outputBindingCounts.get(binding.template_port_id) ?? 0) + 1)
    }

    for (const input of template.template_inputs) {
      if (!inputBindingCounts.has(input.input_id)) return {
        message: translate('workflowEditor.validation.inputBindingMissing', { input: input.input_id }),
        boundaryKind: 'entry',
        bindingId: input.input_id,
      }
    }
    for (const output of template.template_outputs) {
      if (!outputBindingCounts.has(output.output_id)) return {
        message: translate('workflowEditor.validation.outputBindingMissing', { output: output.output_id }),
        boundaryKind: 'result',
        bindingId: output.output_id,
      }
    }
    return null
  }

  function applyWorkflowValidationIssue(issue: WorkflowValidationIssue): void {
    options.setErrorMessage(issue.message)
    options.setStatusMessage(issue.bindingId
      ? translate('workflowEditor.validation.inspectBinding', { binding: issue.bindingId })
      : null)
    options.clearTransientUi()
    if (issue.edgeId && options.graphEdges.value.some((edge) => edge.edge_id === issue.edgeId)) {
      options.setSelection({ edgeId: issue.edgeId, nodeId: null, boundaryKind: null })
      return
    }
    if (issue.nodeId && options.graphNodes.value.some((node) => node.node.node_id === issue.nodeId)) {
      options.focusGraphNode(issue.nodeId)
      return
    }
    if (issue.boundaryKind) {
      options.setSelection({ edgeId: null, nodeId: null, boundaryKind: issue.boundaryKind })
    }
  }

  return {
    runWorkflowPreflight,
    applyWorkflowValidationIssue,
  }
}

function registerInputUsage<NodeView extends WorkflowPreflightNodeView>(inputUsage: Map<string, string[]>, node: NodeView, port: NodePortDefinition, sourceLabel: string): WorkflowValidationIssue | null {
  const inputKey = `${node.node.node_id}.${port.name}`
  const sources = inputUsage.get(inputKey) ?? []
  sources.push(sourceLabel)
  inputUsage.set(inputKey, sources)
  if (sources.length > 1 && !port.multiple) {
    return {
      message: translate('workflowEditor.validation.multipleInputSources', {
        port: inputKey,
        sources: sources.join(translate('workflowEditor.feedback.listSeparator')),
      }),
      nodeId: node.node.node_id,
    }
  }
  return null
}

function findDuplicateValue(values: string[]): string | null {
  const seen = new Set<string>()
  for (const value of values) {
    if (seen.has(value)) return value
    seen.add(value)
  }
  return null
}

function duplicateIdMessage(kind: 'node' | 'edge' | 'appInput' | 'appOutput' | 'nodeGroup' | 'publicBinding', id: string): string {
  return translate('workflowEditor.validation.duplicateId', {
    kind: translate(`workflowEditor.validation.kinds.${kind}`),
    id,
  })
}

function findBindingBoundaryKind(application: FlowApplication, bindingId: string): WorkflowBoundaryKind | undefined {
  const binding = application.bindings.find((item) => item.binding_id === bindingId)
  if (!binding) return undefined
  return binding.direction === 'input' ? 'entry' : 'result'
}
