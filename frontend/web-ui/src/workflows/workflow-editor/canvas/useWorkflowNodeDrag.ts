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
  startX: number
  startY: number
  positions: { id: string; x: number; y: number }[]
  hasMoved: boolean
}

export interface WorkflowNodeDragOptions<NodeView extends WorkflowNodeDragNodeView> {
  graphNodes: Ref<NodeView[]>
  connectionDraft: Ref<WorkflowConnectionDraftState | null>
  screenToWorld: (clientX: number, clientY: number) => { x: number; y: number }
  selectNode: (nodeId: string) => void
  selectedNodeIds?: Ref<Set<string>>
  isBusy?: () => boolean
  onMoved?: () => void
  onStop?: () => void
}

export function useWorkflowNodeDrag<NodeView extends WorkflowNodeDragNodeView>(options: WorkflowNodeDragOptions<NodeView>) {
  const nodeDragState = ref<WorkflowNodeDragState | null>(null)
  let targets = new Map<string, NodeView>()
  let pending: { x: number; y: number } | null = null
  let frame = 0

  function startNodeDrag(event: MouseEvent, node: NodeView): void {
    if (event.button !== 0 || event.ctrlKey || options.isBusy?.() || options.connectionDraft.value) return
    const worldPosition = options.screenToWorld(event.clientX, event.clientY)
    if (!options.selectedNodeIds?.value.has(node.node.node_id)) options.selectNode(node.node.node_id)
    const ids = options.selectedNodeIds?.value ?? new Set([node.node.node_id])
    targets = new Map(options.graphNodes.value.filter(n => ids.has(n.node.node_id)).map(n => [n.node.node_id, n]))
    nodeDragState.value = {
      nodeId: node.node.node_id,
      startX: worldPosition.x,
      startY: worldPosition.y,
      positions: [...targets.values()].map(n => ({ id: n.node.node_id, x: n.x, y: n.y })),
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
    pending = options.screenToWorld(event.clientX, event.clientY)
    if (!frame) frame = requestAnimationFrame(renderMove)
  }

  function renderMove(): void {
    frame = 0
    const drag = nodeDragState.value
    if (!drag || !pending) return
    const dx = Math.round(pending.x - drag.startX), dy = Math.round(pending.y - drag.startY)
    drag.hasMoved ||= dx !== 0 || dy !== 0
    for (const initial of drag.positions) {
      const node = targets.get(initial.id)
      if (!node) continue
      node.x = initial.x + dx
      node.y = initial.y + dy
      node.node.ui_state = { ...node.node.ui_state, x: node.x, y: node.y, width: node.width }
    }
  }

  function stopNodeDrag(): void {
    cancelAnimationFrame(frame)
    renderMove()
    pending = null
    targets.clear()
    const hasMoved = nodeDragState.value?.hasMoved === true
    nodeDragState.value = null
    document.removeEventListener('mousemove', moveDraggedNode)
    document.removeEventListener('mouseup', stopNodeDrag)
    window.removeEventListener('blur', stopNodeDrag)
    if (hasMoved) { options.onMoved?.(); options.onStop?.() }
  }

  return {
    nodeDragState,
    startNodeDrag,
    stopNodeDrag,
  }
}
