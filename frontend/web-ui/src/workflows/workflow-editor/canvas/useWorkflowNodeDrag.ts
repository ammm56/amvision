import { ref, type Ref } from 'vue'

import type { WorkflowConnectionDraftState } from './useWorkflowPortConnections'
import { isPrimaryMouseButtonPressed } from './workflowMouseDrag'

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
  hasMoved: boolean
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
    if (event.button !== 0 || options.connectionDraft.value) return
    const worldPosition = options.screenToWorld(event.clientX, event.clientY)
    options.selectNode(node.node.node_id)
    nodeDragState.value = {
      nodeId: node.node.node_id,
      offsetX: worldPosition.x - node.x,
      offsetY: worldPosition.y - node.y,
      hasMoved: false,
    }
    event.preventDefault()
    document.addEventListener('mousemove', moveDraggedNode)
    document.addEventListener('mouseup', stopNodeDrag)
    window.addEventListener('blur', stopNodeDrag)
  }

  function moveDraggedNode(event: MouseEvent): void {
    const drag = nodeDragState.value
    if (!drag) return
    if (!isPrimaryMouseButtonPressed(event)) {
      stopNodeDrag()
      return
    }
    const targetNode = options.graphNodes.value.find((node) => node.node.node_id === drag.nodeId)
    if (!targetNode) {
      stopNodeDrag()
      return
    }
    const worldPosition = options.screenToWorld(event.clientX, event.clientY)
    const nextX = Math.round(worldPosition.x - drag.offsetX)
    const nextY = Math.round(worldPosition.y - drag.offsetY)
    drag.hasMoved = drag.hasMoved || nextX !== targetNode.x || nextY !== targetNode.y
    targetNode.x = nextX
    targetNode.y = nextY
    targetNode.node.ui_state = { ...targetNode.node.ui_state, x: targetNode.x, y: targetNode.y, width: targetNode.width }
  }

  function stopNodeDrag(): void {
    const hasMoved = nodeDragState.value?.hasMoved === true
    nodeDragState.value = null
    document.removeEventListener('mousemove', moveDraggedNode)
    document.removeEventListener('mouseup', stopNodeDrag)
    window.removeEventListener('blur', stopNodeDrag)
    if (hasMoved) options.onStop?.()
  }

  return {
    nodeDragState,
    startNodeDrag,
    stopNodeDrag,
  }
}
