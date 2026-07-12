import { ref, type Ref } from 'vue'

import type { WorkflowConnectionDraftState } from './useWorkflowPortConnections'

export interface WorkflowNodeDragNodeView {
  node: {
    node_id: string
    ui_state: Record<string, unknown>
  }
  x: number
  y: number
  width: number
}

interface WorkflowNodeDragState {
  nodeId: string
  offsetX: number
  offsetY: number
}

export interface WorkflowNodeDragOptions<NodeView extends WorkflowNodeDragNodeView> {
  graphNodes: Ref<NodeView[]>
  connectionDraft: Ref<WorkflowConnectionDraftState | null>
  screenToWorld: (clientX: number, clientY: number) => { x: number; y: number }
  selectNode: (nodeId: string) => void
  onStop?: () => void
}

export function useWorkflowNodeDrag<NodeView extends WorkflowNodeDragNodeView>(options: WorkflowNodeDragOptions<NodeView>) {
  const nodeDragState = ref<WorkflowNodeDragState | null>(null)

  function startNodeDrag(event: MouseEvent, node: NodeView): void {
    if (options.connectionDraft.value) return
    const worldPosition = options.screenToWorld(event.clientX, event.clientY)
    options.selectNode(node.node.node_id)
    nodeDragState.value = {
      nodeId: node.node.node_id,
      offsetX: worldPosition.x - node.x,
      offsetY: worldPosition.y - node.y,
    }
    event.preventDefault()
    document.addEventListener('mousemove', moveDraggedNode)
    document.addEventListener('mouseup', stopNodeDrag)
  }

  function moveDraggedNode(event: MouseEvent): void {
    const drag = nodeDragState.value
    if (!drag) return
    const targetNode = options.graphNodes.value.find((node) => node.node.node_id === drag.nodeId)
    if (!targetNode) return
    const worldPosition = options.screenToWorld(event.clientX, event.clientY)
    targetNode.x = Math.round(worldPosition.x - drag.offsetX)
    targetNode.y = Math.round(worldPosition.y - drag.offsetY)
    targetNode.node.ui_state = { ...targetNode.node.ui_state, x: targetNode.x, y: targetNode.y, width: targetNode.width }
  }

  function stopNodeDrag(): void {
    const wasDragging = Boolean(nodeDragState.value)
    nodeDragState.value = null
    document.removeEventListener('mousemove', moveDraggedNode)
    document.removeEventListener('mouseup', stopNodeDrag)
    if (wasDragging) options.onStop?.()
  }

  return {
    nodeDragState,
    startNodeDrag,
    stopNodeDrag,
  }
}
