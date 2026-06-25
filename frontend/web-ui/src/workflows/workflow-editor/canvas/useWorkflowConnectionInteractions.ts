import type { ComputedRef, Ref } from 'vue'

import type { WorkflowBoundaryNodeView } from '../bindings/useWorkflowBoundaryNodes'
import type { FlowApplicationBinding, NodePortDefinition, WorkflowGraphEdge } from '../types'
import type { WorkflowGraphLinkView } from '../geometry/useWorkflowGraphGeometry'
import type { WorkflowConnectionDraftAnchor, WorkflowConnectionDraftState, WorkflowPortDirection } from './useWorkflowPortConnections'

export interface WorkflowConnectionInteractionNodeView {
  node: {
    node_id: string
  }
  outputs: NodePortDefinition[]
}

export interface WorkflowConnectionInteractionOptions<NodeView extends WorkflowConnectionInteractionNodeView> {
  graphNodes: Ref<NodeView[]>
  graphLinks: ComputedRef<WorkflowGraphLinkView[]>
  selectedEdge: ComputedRef<WorkflowGraphEdge | null>
  connectionDraft: Ref<WorkflowConnectionDraftState | null>
  portX: (node: NodeView, direction: WorkflowPortDirection) => number
  portY: (node: NodeView, portName: string, direction: WorkflowPortDirection) => number
  boundaryPortX: (boundary: WorkflowBoundaryNodeView) => number
  boundaryPortY: (boundary: WorkflowBoundaryNodeView, bindingId: string) => number
  findInputEdge: (nodeId: string, portName: string) => WorkflowGraphEdge | null
  startPortConnectionDraft: (event: MouseEvent, anchor: WorkflowConnectionDraftAnchor) => boolean
  selectNode: (nodeId: string, options?: { preserveConnectionDraft?: boolean }) => void
  selectEdge: (edgeId: string, options?: { preserveConnectionDraft?: boolean }) => void
  selectApplicationBoundary: (boundaryKind: 'entry' | 'result', options?: { preserveConnectionDraft?: boolean }) => void
  clearErrorMessage: () => void
}

export function useWorkflowConnectionInteractions<NodeView extends WorkflowConnectionInteractionNodeView>(
  options: WorkflowConnectionInteractionOptions<NodeView>,
) {
  function isSelectedEdgeEndpoint(nodeId: string, portName: string, direction: WorkflowPortDirection): boolean {
    const edge = options.selectedEdge.value
    if (!edge) return false
    return direction === 'input'
      ? edge.target_node_id === nodeId && edge.target_port === portName
      : edge.source_node_id === nodeId && edge.source_port === portName
  }

  function isDraftAnchorPort(nodeId: string, portName: string, direction: WorkflowPortDirection): boolean {
    const draft = options.connectionDraft.value
    return Boolean(draft && draft.anchorNodeId === nodeId && draft.anchorPort === portName && draft.anchorDirection === direction)
  }

  function startPortConnection(event: MouseEvent, node: NodeView, port: NodePortDefinition, direction: WorkflowPortDirection): void {
    if (event.button !== 0) return
    const existingInputEdge = direction === 'input' ? options.findInputEdge(node.node.node_id, port.name) : null
    if (existingInputEdge) {
      startEdgeTargetReconnect(event, existingInputEdge.edge_id)
      return
    }
    startConnectionDraft(event, node, port, direction)
  }

  function startBoundaryPortConnection(event: MouseEvent, boundary: WorkflowBoundaryNodeView, binding: FlowApplicationBinding): void {
    if (event.button !== 0) return
    const started = options.startPortConnectionDraft(event, {
      anchorDirection: boundary.portDirection,
      anchorNodeId: boundary.id,
      anchorPort: binding.binding_id,
      anchorX: options.boundaryPortX(boundary),
      anchorY: options.boundaryPortY(boundary, binding.binding_id),
      replacingEdgeId: null,
    })
    if (!started) return
    options.selectApplicationBoundary(boundary.kind, { preserveConnectionDraft: true })
    options.clearErrorMessage()
  }

  function startConnectionDraft(
    event: MouseEvent,
    node: NodeView,
    port: NodePortDefinition,
    anchorDirection: WorkflowPortDirection,
    replacingEdgeId: string | null = null,
  ): void {
    const started = options.startPortConnectionDraft(event, {
      anchorDirection,
      anchorNodeId: node.node.node_id,
      anchorPort: port.name,
      anchorX: options.portX(node, anchorDirection),
      anchorY: options.portY(node, port.name, anchorDirection),
      replacingEdgeId,
    })
    if (!started) return
    options.selectNode(node.node.node_id, { preserveConnectionDraft: true })
    options.clearErrorMessage()
  }

  function startEdgeTargetReconnect(event: MouseEvent, edgeId: string): void {
    const link = options.graphLinks.value.find((item) => item.edgeId === edgeId && item.linkKind === 'edge')
    if (!link?.edge) return
    const edge = link.edge
    const sourceNode = options.graphNodes.value.find((node) => node.node.node_id === edge.source_node_id)
    const sourcePort = sourceNode?.outputs.find((port) => port.name === edge.source_port)
    if (!sourceNode || !sourcePort) return
    const started = options.startPortConnectionDraft(event, {
      anchorDirection: 'output',
      anchorNodeId: sourceNode.node.node_id,
      anchorPort: sourcePort.name,
      anchorX: link.sourceX,
      anchorY: link.sourceY,
      replacingEdgeId: edgeId,
    })
    if (!started) return
    options.selectEdge(edgeId, { preserveConnectionDraft: true })
    options.clearErrorMessage()
  }

  return {
    isSelectedEdgeEndpoint,
    isDraftAnchorPort,
    startPortConnection,
    startBoundaryPortConnection,
    startEdgeTargetReconnect,
  }
}
