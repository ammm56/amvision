import { ref } from 'vue'

export type WorkflowPortDirection = 'input' | 'output'

export interface WorkflowPortReference {
  nodeId: string
  portName: string
  direction: WorkflowPortDirection
}

export interface WorkflowConnectionDraftState {
  anchorDirection: WorkflowPortDirection
  anchorNodeId: string
  anchorPort: string
  anchorX: number
  anchorY: number
  pointerX: number
  pointerY: number
  startClientX: number
  startClientY: number
  hasMoved: boolean
  replacingEdgeId?: string | null
}

export interface WorkflowConnectionDraftAnchor {
  anchorDirection: WorkflowPortDirection
  anchorNodeId: string
  anchorPort: string
  anchorX: number
  anchorY: number
  replacingEdgeId?: string | null
}

export interface WorkflowPortConnectionOptions {
  screenToWorld: (clientX: number, clientY: number) => { x: number; y: number }
  connectDraftToPort: (draft: WorkflowConnectionDraftState, targetPort: WorkflowPortReference) => boolean
  openNodePickerFromConnectionDraft: (draft: WorkflowConnectionDraftState, event: MouseEvent) => void
  suppressNodeClickOnce: () => void
  clearNodePicker: () => void
}

function resolvePortElement(clientX: number, clientY: number): WorkflowPortReference | null {
  const element = document.elementFromPoint(clientX, clientY)
  const portElement = element instanceof Element ? element.closest<HTMLElement>('.workflow-graph-port') : null
  if (!portElement) return null
  const nodeId = portElement.dataset.nodeId
  const portName = portElement.dataset.portName
  const direction = portElement.dataset.portDirection
  if (!nodeId || !portName || (direction !== 'input' && direction !== 'output')) return null
  return { nodeId, portName, direction }
}

export function useWorkflowPortConnections(options: WorkflowPortConnectionOptions) {
  const connectionDraft = ref<WorkflowConnectionDraftState | null>(null)

  function startPortConnectionDraft(event: MouseEvent, anchor: WorkflowConnectionDraftAnchor): boolean {
    if (event.button !== 0) return false
    const pointer = options.screenToWorld(event.clientX, event.clientY)
    connectionDraft.value = {
      ...anchor,
      pointerX: pointer.x,
      pointerY: pointer.y,
      startClientX: event.clientX,
      startClientY: event.clientY,
      hasMoved: false,
      replacingEdgeId: anchor.replacingEdgeId ?? null,
    }
    event.preventDefault()
    document.addEventListener('mousemove', movePortConnection)
    document.addEventListener('mouseup', stopPortConnection)
    return true
  }

  function movePortConnection(event: MouseEvent): void {
    if (!connectionDraft.value) return
    const pointer = options.screenToWorld(event.clientX, event.clientY)
    const movedDistance = Math.hypot(event.clientX - connectionDraft.value.startClientX, event.clientY - connectionDraft.value.startClientY)
    connectionDraft.value = {
      ...connectionDraft.value,
      pointerX: pointer.x,
      pointerY: pointer.y,
      hasMoved: connectionDraft.value.hasMoved || movedDistance > 4,
    }
  }

  function stopPortConnection(event?: MouseEvent): void {
    const draft = connectionDraft.value
    let didConnect = false
    let didOpenNodePicker = false
    if (draft && event) {
      const targetPort = resolvePortElement(event.clientX, event.clientY)
      if (targetPort) {
        didConnect = options.connectDraftToPort(draft, targetPort)
      } else if (draft.hasMoved) {
        options.openNodePickerFromConnectionDraft(draft, event)
        didOpenNodePicker = true
      }
      if (draft.hasMoved || didConnect) {
        options.suppressNodeClickOnce()
      }
    }
    if (!didOpenNodePicker) {
      options.clearNodePicker()
    }
    connectionDraft.value = null
    document.removeEventListener('mousemove', movePortConnection)
    document.removeEventListener('mouseup', stopPortConnection)
  }

  return {
    connectionDraft,
    startPortConnectionDraft,
    stopPortConnection,
  }
}
