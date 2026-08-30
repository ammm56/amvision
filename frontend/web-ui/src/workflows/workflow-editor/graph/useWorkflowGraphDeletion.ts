import type { Ref } from 'vue'

import { translate } from '@/platform/i18n'
import type { WorkflowBoundaryKind } from '../bindings/useWorkflowPublicBindings'
import type {
  FlowApplicationBinding,
  WorkflowGraphEdge,
  WorkflowGraphGroup,
  WorkflowGraphInput,
  WorkflowGraphOutput,
} from '../types'

export interface WorkflowDeletionGraphNode {
  node: {
    node_id: string
  }
}

export interface WorkflowDeletionSelection {
  nodeId: string | null
  edgeId: string | null
  boundaryKind: WorkflowBoundaryKind | null
}

export interface WorkflowGraphDeletionOptions<NodeView extends WorkflowDeletionGraphNode> {
  graphNodes: Ref<NodeView[]>
  graphEdges: Ref<WorkflowGraphEdge[]>
  graphGroups: Ref<WorkflowGraphGroup[]>
  templateInputs: Ref<WorkflowGraphInput[]>
  templateOutputs: Ref<WorkflowGraphOutput[]>
  applicationBindingsDraft: Ref<FlowApplicationBinding[]>
  removePreviewInputStates: (bindingIds: Set<string>) => void
  setSelection: (selection: WorkflowDeletionSelection) => void
  clearTransientUi: () => void
  setStatusMessage: (message: string | null) => void
}

export function useWorkflowGraphDeletion<NodeView extends WorkflowDeletionGraphNode>(options: WorkflowGraphDeletionOptions<NodeView>) {
  function deleteGraphNode(nodeId: string | null | undefined): boolean {
    if (!nodeId) return false
    const removedInputIds = new Set(
      options.templateInputs.value
        .filter((input) => input.target_node_id === nodeId)
        .map((input) => input.input_id),
    )
    const removedOutputIds = new Set(
      options.templateOutputs.value
        .filter((output) => output.source_node_id === nodeId)
        .map((output) => output.output_id),
    )
    const removedBindingIds = new Set(
      options.applicationBindingsDraft.value
        .filter((binding) => removedInputIds.has(binding.template_port_id) || removedOutputIds.has(binding.template_port_id))
        .map((binding) => binding.binding_id),
    )

    options.graphNodes.value = options.graphNodes.value.filter((node) => node.node.node_id !== nodeId)
    options.graphEdges.value = options.graphEdges.value.filter((edge) => edge.source_node_id !== nodeId && edge.target_node_id !== nodeId)
    options.graphGroups.value.forEach((group) => {
      group.member_node_ids = group.member_node_ids.filter((memberNodeId) => memberNodeId !== nodeId)
    })
    options.templateInputs.value = options.templateInputs.value.filter((input) => !removedInputIds.has(input.input_id))
    options.templateOutputs.value = options.templateOutputs.value.filter((output) => !removedOutputIds.has(output.output_id))
    options.applicationBindingsDraft.value = options.applicationBindingsDraft.value.filter(
      (binding) => !removedInputIds.has(binding.template_port_id) && !removedOutputIds.has(binding.template_port_id),
    )
    if (removedBindingIds.size > 0) {
      options.removePreviewInputStates(removedBindingIds)
    }

    options.clearTransientUi()
    options.setSelection({
      nodeId: options.graphNodes.value[0]?.node.node_id ?? null,
      edgeId: null,
      boundaryKind: null,
    })
    options.setStatusMessage(translate('workflowEditor.feedback.nodeDeleted'))
    return true
  }

  function deleteGraphEdge(edgeId: string | null | undefined): boolean {
    if (!edgeId) return false
    options.graphEdges.value = options.graphEdges.value.filter((edge) => edge.edge_id !== edgeId)
    options.clearTransientUi()
    options.setSelection({ nodeId: null, edgeId: null, boundaryKind: null })
    options.setStatusMessage(translate('workflowEditor.feedback.edgeDeleted'))
    return true
  }

  return {
    deleteGraphNode,
    deleteGraphEdge,
  }
}
