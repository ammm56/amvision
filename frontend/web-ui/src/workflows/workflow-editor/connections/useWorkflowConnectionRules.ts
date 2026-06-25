import type { ComputedRef, Ref } from 'vue'

import { buildPublicPortMetadata } from '../bindings/useWorkflowPublicBindings'
import type { WorkflowConnectionDraftState, WorkflowPortReference } from '../canvas/useWorkflowPortConnections'
import type {
  FlowApplicationBinding,
  NodePortDefinition,
  WorkflowGraphEdge,
  WorkflowGraphInput,
  WorkflowGraphOutput,
} from '../types'

export interface WorkflowConnectionNodeView {
  node: {
    node_id: string
    node_type_id: string
  }
  inputs: NodePortDefinition[]
  outputs: NodePortDefinition[]
}

export interface WorkflowConnectionSelection {
  nodeId: string | null
  edgeId: string | null
  boundaryKind: 'entry' | 'result' | null
}

export interface WorkflowConnectionRuleOptions<NodeView extends WorkflowConnectionNodeView> {
  graphNodes: Ref<NodeView[]>
  graphEdges: Ref<WorkflowGraphEdge[]>
  templateInputs: Ref<WorkflowGraphInput[]>
  templateOutputs: Ref<WorkflowGraphOutput[]>
  appInputBindings: ComputedRef<FlowApplicationBinding[]>
  appOutputBindings: ComputedRef<FlowApplicationBinding[]>
  templateInputById: ComputedRef<Map<string, WorkflowGraphInput>>
  templateOutputById: ComputedRef<Map<string, WorkflowGraphOutput>>
  appEntryBoundaryId: string
  appResultBoundaryId: string
  getBindingPayloadTypeId: (binding: FlowApplicationBinding) => string
  setPreviewInputStateForBinding: (binding: FlowApplicationBinding) => void
  setSelection: (selection: WorkflowConnectionSelection) => void
  selectApplicationBoundary: (boundaryKind: 'entry' | 'result') => void
  setStatusMessage: (message: string | null) => void
  setErrorMessage: (message: string | null) => void
}

export function portsCanConnect(sourcePort: NodePortDefinition, targetPort: NodePortDefinition): boolean {
  if (!sourcePort.payload_type_id || !targetPort.payload_type_id) return true
  return sourcePort.payload_type_id === targetPort.payload_type_id
}

function createGraphEdgeId(sourceNodeId: string, sourcePort: string, targetNodeId: string, targetPort: string): string {
  return `${sourceNodeId}_${sourcePort}_to_${targetNodeId}_${targetPort}`.replace(/[^a-zA-Z0-9]+/g, '_').replace(/^_+|_+$/g, '').toLowerCase() || 'edge'
}

export function useWorkflowConnectionRules<NodeView extends WorkflowConnectionNodeView>(options: WorkflowConnectionRuleOptions<NodeView>) {
  function findInputEdge(nodeId: string, portName: string): WorkflowGraphEdge | null {
    return [...options.graphEdges.value].reverse().find((edge) => edge.target_node_id === nodeId && edge.target_port === portName) ?? null
  }

  function findOutputEdge(nodeId: string, portName: string): WorkflowGraphEdge | null {
    return [...options.graphEdges.value].reverse().find((edge) => edge.source_node_id === nodeId && edge.source_port === portName) ?? null
  }

  function getConnectionDraftPayloadTypeId(draft: WorkflowConnectionDraftState): string | null {
    const anchorNode = options.graphNodes.value.find((node) => node.node.node_id === draft.anchorNodeId)
    if (!anchorNode) return null
    const port = draft.anchorDirection === 'output'
      ? anchorNode.outputs.find((item) => item.name === draft.anchorPort)
      : anchorNode.inputs.find((item) => item.name === draft.anchorPort)
    return port?.payload_type_id ?? null
  }

  function connectConnectionDraftToNewNode(draft: WorkflowConnectionDraftState, graphNode: NodeView): boolean {
    const anchorNode = options.graphNodes.value.find((node) => node.node.node_id === draft.anchorNodeId)
    if (!anchorNode) return false
    if (draft.anchorDirection === 'output') {
      const sourcePort = anchorNode.outputs.find((port) => port.name === draft.anchorPort)
      if (!sourcePort) return false
      const targetPort = graphNode.inputs.find((port) => portsCanConnect(sourcePort, port))
      if (!targetPort) {
        options.setErrorMessage('选中的节点没有兼容的输入端口')
        return false
      }
      return connectOutputToInput({ nodeId: draft.anchorNodeId, portName: draft.anchorPort, direction: 'output' }, { nodeId: graphNode.node.node_id, portName: targetPort.name, direction: 'input' }, draft.replacingEdgeId)
    }
    const targetPort = anchorNode.inputs.find((port) => port.name === draft.anchorPort)
    if (!targetPort) return false
    const sourcePort = graphNode.outputs.find((port) => portsCanConnect(port, targetPort))
    if (!sourcePort) {
      options.setErrorMessage('选中的节点没有兼容的输出端口')
      return false
    }
    return connectOutputToInput({ nodeId: graphNode.node.node_id, portName: sourcePort.name, direction: 'output' }, { nodeId: draft.anchorNodeId, portName: draft.anchorPort, direction: 'input' }, draft.replacingEdgeId)
  }

  function connectDraftToPort(draft: WorkflowConnectionDraftState, targetPort: WorkflowPortReference): boolean {
    if (draft.anchorDirection === 'output') {
      if (targetPort.direction !== 'input') {
        if (draft.hasMoved) options.setErrorMessage('请连接到输入端口')
        return false
      }
      return connectOutputToInput({ nodeId: draft.anchorNodeId, portName: draft.anchorPort, direction: 'output' }, targetPort, draft.replacingEdgeId)
    }
    if (targetPort.direction !== 'output') {
      if (draft.hasMoved) options.setErrorMessage('请连接到输出端口')
      return false
    }
    return connectOutputToInput(targetPort, { nodeId: draft.anchorNodeId, portName: draft.anchorPort, direction: 'input' }, draft.replacingEdgeId)
  }

  function connectOutputToInput(sourcePortRef: WorkflowPortReference, targetPortRef: WorkflowPortReference, replacingEdgeId?: string | null): boolean {
    if (sourcePortRef.nodeId === options.appEntryBoundaryId) {
      return connectAppEntryBindingToNode(sourcePortRef.portName, targetPortRef)
    }
    if (targetPortRef.nodeId === options.appResultBoundaryId) {
      return connectNodeOutputToAppResultBinding(sourcePortRef, targetPortRef.portName)
    }
    if (sourcePortRef.nodeId === options.appResultBoundaryId || targetPortRef.nodeId === options.appEntryBoundaryId) {
      options.setErrorMessage('App Entry 只能连接到节点输入，节点输出只能连接到 App Result')
      return false
    }
    if (sourcePortRef.nodeId === targetPortRef.nodeId) {
      options.setErrorMessage('不能把节点输出连接到同一个节点的输入')
      return false
    }
    const sourceNode = options.graphNodes.value.find((node) => node.node.node_id === sourcePortRef.nodeId)
    const targetNode = options.graphNodes.value.find((node) => node.node.node_id === targetPortRef.nodeId)
    if (!sourceNode || !targetNode) return false
    const sourcePort = sourceNode.outputs.find((port) => port.name === sourcePortRef.portName)
    const inputPort = targetNode.inputs.find((port) => port.name === targetPortRef.portName)
    if (!sourcePort || !inputPort) return false
    if (!portsCanConnect(sourcePort, inputPort)) {
      options.setErrorMessage(`端口类型不匹配：${sourcePort.payload_type_id || 'unknown'} -> ${inputPort.payload_type_id || 'unknown'}`)
      return false
    }
    const existingTemplateInput = options.templateInputs.value.find((input) => input.target_node_id === targetPortRef.nodeId && input.target_port === targetPortRef.portName)
    if (existingTemplateInput && !inputPort.multiple) {
      options.setErrorMessage('该输入端口已公开为应用输入，请先删除公开接口再连接普通节点')
      return false
    }
    const nextEdge: WorkflowGraphEdge = {
      edge_id: createGraphEdgeId(sourcePortRef.nodeId, sourcePortRef.portName, targetPortRef.nodeId, targetPortRef.portName),
      source_node_id: sourcePortRef.nodeId,
      source_port: sourcePortRef.portName,
      target_node_id: targetPortRef.nodeId,
      target_port: targetPortRef.portName,
      metadata: {},
    }
    options.graphEdges.value = [
      ...options.graphEdges.value.filter((edge) => {
        if (replacingEdgeId && edge.edge_id === replacingEdgeId) return false
        if (edge.edge_id === nextEdge.edge_id) return false
        if (!inputPort.multiple && edge.target_node_id === nextEdge.target_node_id && edge.target_port === nextEdge.target_port) return false
        return true
      }),
      nextEdge,
    ]
    options.setSelection({ nodeId: null, edgeId: nextEdge.edge_id, boundaryKind: null })
    options.setStatusMessage('已更新连线')
    options.setErrorMessage(null)
    return true
  }

  function connectAppEntryBindingToNode(bindingId: string, targetPortRef: WorkflowPortReference): boolean {
    const binding = options.appInputBindings.value.find((item) => item.binding_id === bindingId)
    const templateInput = binding ? options.templateInputById.value.get(binding.template_port_id) : null
    const targetNode = options.graphNodes.value.find((node) => node.node.node_id === targetPortRef.nodeId)
    const targetPort = targetNode?.inputs.find((port) => port.name === targetPortRef.portName)
    if (!binding || !templateInput || !targetNode || !targetPort || targetPortRef.direction !== 'input') return false
    const previousPayloadTypeId = options.getBindingPayloadTypeId(binding)
    const conflictingInput = options.templateInputs.value.find((input) => input !== templateInput && input.target_node_id === targetNode.node.node_id && input.target_port === targetPort.name)
    if ((findInputEdge(targetNode.node.node_id, targetPort.name) || conflictingInput) && !targetPort.multiple) {
      options.setErrorMessage('该输入端口已有输入来源，请先删除现有连线或公开接口')
      return false
    }
    templateInput.target_node_id = targetNode.node.node_id
    templateInput.target_port = targetPort.name
    templateInput.payload_type_id = targetPort.payload_type_id
    templateInput.required = binding.required
    binding.config = { ...binding.config, payload_type_id: targetPort.payload_type_id }
    binding.metadata = { ...binding.metadata, ...buildPublicPortMetadata(targetNode, targetPort) }
    if (previousPayloadTypeId !== targetPort.payload_type_id) {
      options.setPreviewInputStateForBinding(binding)
    }
    options.selectApplicationBoundary('entry')
    options.setStatusMessage('已更新应用输入连接')
    options.setErrorMessage(null)
    return true
  }

  function connectNodeOutputToAppResultBinding(sourcePortRef: WorkflowPortReference, bindingId: string): boolean {
    const binding = options.appOutputBindings.value.find((item) => item.binding_id === bindingId)
    const templateOutput = binding ? options.templateOutputById.value.get(binding.template_port_id) : null
    const sourceNode = options.graphNodes.value.find((node) => node.node.node_id === sourcePortRef.nodeId)
    const sourcePort = sourceNode?.outputs.find((port) => port.name === sourcePortRef.portName)
    if (!binding || !templateOutput || !sourceNode || !sourcePort || sourcePortRef.direction !== 'output') return false
    templateOutput.source_node_id = sourceNode.node.node_id
    templateOutput.source_port = sourcePort.name
    templateOutput.payload_type_id = sourcePort.payload_type_id
    binding.config = { ...binding.config, payload_type_id: sourcePort.payload_type_id }
    binding.metadata = { ...binding.metadata, ...buildPublicPortMetadata(sourceNode, sourcePort) }
    options.selectApplicationBoundary('result')
    options.setStatusMessage('已更新应用输出连接')
    options.setErrorMessage(null)
    return true
  }

  return {
    portsCanConnect,
    findInputEdge,
    findOutputEdge,
    getConnectionDraftPayloadTypeId,
    connectConnectionDraftToNewNode,
    connectDraftToPort,
    connectOutputToInput,
  }
}
