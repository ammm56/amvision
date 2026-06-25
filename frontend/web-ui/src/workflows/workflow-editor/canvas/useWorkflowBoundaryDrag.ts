import { shallowRef } from 'vue'

export interface WorkflowBoundaryDragState<BoundaryKind extends string> {
  boundaryKind: BoundaryKind
  offsetX: number
  offsetY: number
}

export interface WorkflowBoundaryDragTarget<BoundaryKind extends string> {
  kind: BoundaryKind
  x: number
  y: number
}

export interface WorkflowBoundaryDragOptions<BoundaryKind extends string> {
  screenToWorld: (clientX: number, clientY: number) => { x: number; y: number }
  canStart?: () => boolean
  onStart?: (boundaryKind: BoundaryKind) => void
  updateBoundaryPosition: (boundaryKind: BoundaryKind, position: { x: number; y: number }) => void
}

export function useWorkflowBoundaryDrag<BoundaryKind extends string>(options: WorkflowBoundaryDragOptions<BoundaryKind>) {
  const boundaryDragState = shallowRef<WorkflowBoundaryDragState<BoundaryKind> | null>(null)

  function startBoundaryDrag(event: MouseEvent, boundary: WorkflowBoundaryDragTarget<BoundaryKind>): void {
    if (event.button !== 0 || options.canStart?.() === false) return
    const worldPosition = options.screenToWorld(event.clientX, event.clientY)
    boundaryDragState.value = {
      boundaryKind: boundary.kind,
      offsetX: worldPosition.x - boundary.x,
      offsetY: worldPosition.y - boundary.y,
    }
    options.onStart?.(boundary.kind)
    event.preventDefault()
    document.addEventListener('mousemove', moveDraggedBoundary)
    document.addEventListener('mouseup', stopBoundaryDrag)
  }

  function moveDraggedBoundary(event: MouseEvent): void {
    const drag = boundaryDragState.value
    if (!drag) return
    const worldPosition = options.screenToWorld(event.clientX, event.clientY)
    options.updateBoundaryPosition(drag.boundaryKind, {
      x: Math.round(worldPosition.x - drag.offsetX),
      y: Math.round(worldPosition.y - drag.offsetY),
    })
  }

  function stopBoundaryDrag(): void {
    boundaryDragState.value = null
    document.removeEventListener('mousemove', moveDraggedBoundary)
    document.removeEventListener('mouseup', stopBoundaryDrag)
  }

  return {
    boundaryDragState,
    startBoundaryDrag,
    stopBoundaryDrag,
  }
}
